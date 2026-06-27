from fastapi import FastAPI, APIRouter, HTTPException, Depends, UploadFile, File, Form, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import FileResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field, EmailStr, field_validator
from typing import List, Optional
import uuid
from datetime import datetime, timezone, timedelta, date
import jwt
import bcrypt
import shutil
import re
import secrets
import hashlib
import asyncio
import math

# Resend for email
try:
    import resend
    RESEND_AVAILABLE = True
except ImportError:
    RESEND_AVAILABLE = False

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# JWT Configuration
JWT_SECRET = os.environ.get('JWT_SECRET', 'hr-system-secret-key-2024')
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24

# Admin Master Configuration (from environment variables)
MASTER_ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL', 'geral@olacai.com')
MASTER_ADMIN_PASSWORD_HASH = os.environ.get('ADMIN_PASSWORD_HASH')

# Perfis com acesso de gestão (acesso operacional completo). Todos podem fazer
# tudo; apenas o admin master (por email) cria/gere outros gestores.
MANAGER_ROLES = ["admin", "gerente", "contabilista"]

# Password Reset Configuration
RESET_TOKEN_EXPIRATION_HOURS = 1

# Resend Email Configuration
RESEND_API_KEY = os.environ.get('RESEND_API_KEY')
SENDER_EMAIL = os.environ.get('SENDER_EMAIL', 'onboarding@resend.dev')
# URL do frontend usado nos links de recuperação de palavra-passe.
# Em produção definir FRONTEND_URL no .env (ex.: https://rh.suaempresa.pt)
FRONTEND_URL = os.environ.get('FRONTEND_URL', 'http://localhost:3000')

# Initialize Resend
if RESEND_AVAILABLE and RESEND_API_KEY:
    resend.api_key = RESEND_API_KEY

# Password validation configuration
MIN_PASSWORD_LENGTH = 8

# File upload directory
UPLOAD_DIR = ROOT_DIR / 'uploads'
UPLOAD_DIR.mkdir(exist_ok=True)

# Create the main app
app = FastAPI(title="RH grupo Lisbonb - Sistema de Gestão")

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")

# Security
security = HTTPBearer()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ==================== PASSWORD UTILITIES ====================

def validate_password_strength(password: str) -> tuple[bool, str]:
    """Validate password meets minimum security requirements"""
    if len(password) < MIN_PASSWORD_LENGTH:
        return False, f"A palavra-passe deve ter pelo menos {MIN_PASSWORD_LENGTH} caracteres"
    return True, ""

def validate_photo_data_url(photo):
    """Valida uma foto em data URL (base64). Levanta HTTP 400 se inválida."""
    if photo:
        if not isinstance(photo, str) or not photo.startswith("data:image/"):
            raise HTTPException(status_code=400, detail="Formato de imagem inválido")
        if len(photo) > 4_000_000:  # ~3MB
            raise HTTPException(status_code=400, detail="Imagem demasiado grande (máx. ~3MB)")

def hash_password(password: str) -> str:
    """Hash password using bcrypt"""
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(password: str, hashed: str) -> bool:
    """Verify password against bcrypt hash"""
    try:
        return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))
    except Exception:
        return False

def create_token(user_id: str, email: str, role: str, employee_id: str = None, must_change_password: bool = False) -> str:
    """Create JWT token with user information"""
    payload = {
        "user_id": user_id,
        "email": email,
        "role": role,
        "employee_id": employee_id,
        "must_change_password": must_change_password,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRATION_HOURS)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

# ==================== PASSWORD RESET UTILITIES ====================

def generate_reset_code() -> str:
    """Generate a secure 6-digit code for password reset"""
    return f"{secrets.randbelow(1000000):06d}"

def hash_reset_token(token: str) -> str:
    """Hash the reset token using SHA256 for storage"""
    return hashlib.sha256(token.encode('utf-8')).hexdigest()

def get_password_reset_email_html(user_name: str, reset_code: str) -> str:
    """Generate HTML email template for password reset code"""
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset=\"utf-8\">
        <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">
    </head>
    <body style=\"margin: 0; padding: 0; font-family: Arial, Helvetica, sans-serif; background-color: #f4f4f4;\">
        <table role=\"presentation\" style=\"width: 100%; border-collapse: collapse;\">
            <tr>
                <td style=\"padding: 40px 0;\">
                    <table role=\"presentation\" style=\"width: 600px; margin: 0 auto; background-color: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.1);\">
                        <tr>
                            <td style=\"background-color: #1a365d; padding: 30px; text-align: center;\">
                                <h1 style=\"color: #ffffff; margin: 0; font-size: 24px;\">RH grupo Lisbonb</h1>
                            </td>
                        </tr>
                        <tr>
                            <td style=\"padding: 40px 30px;\">
                                <h2 style=\"color: #1a365d; margin: 0 0 20px 0; font-size: 20px;\">Código de Redefinição</h2>
                                <p style=\"color: #4a5568; font-size: 16px; line-height: 1.6; margin: 0 0 20px 0;\">
                                    Olá <strong>{user_name}</strong>,
                                </p>
                                <p style=\"color: #4a5568; font-size: 16px; line-height: 1.6; margin: 0 0 20px 0;\">
                                    Recebemos um pedido para redefinir a palavra-passe da sua conta. Utilize o código de 6 dígitos abaixo para continuar no site:
                                </p>
                                <div style=\"text-align: center; margin: 30px 0;\">
                                    <div style=\"display: inline-block; padding: 16px 24px; border: 1px solid #e2e8f0; border-radius: 8px; background-color: #f8fafc;\">
                                        <span style=\"font-size: 32px; letter-spacing: 6px; color: #1a365d; font-weight: bold;\">{reset_code}</span>
                                    </div>
                                </div>
                                <p style=\"color: #718096; font-size: 14px; line-height: 1.6; margin: 20px 0 0 0;\">
                                    Este código é válido por <strong>1 hora</strong>. Se não solicitou esta alteração, pode ignorar este email em segurança.
                                </p>
                                <p style=\"color: #718096; font-size: 14px; line-height: 1.6; margin: 10px 0 0 0;\">
                                    Por segurança, não partilhe este código com ninguém.
                                </p>
                            </td>
                        </tr>
                        <tr>
                            <td style=\"background-color: #f7fafc; padding: 20px 30px; text-align: center; border-top: 1px solid #e2e8f0;\">
                                <p style=\"color: #a0aec0; font-size: 12px; margin: 0;\">
                                    © 2024 RH grupo Lisbonb. Todos os direitos reservados.
                                </p>
                                <p style=\"color: #a0aec0; font-size: 12px; margin: 10px 0 0 0;\">
                                    Este é um email automático, por favor não responda.
                                </p>
                            </td>
                        </tr>
                    </table>
                </td>
            </tr>
        </table>
    </body>
    </html>
    """

async def send_password_reset_email(email: str, user_name: str, reset_code: str) -> bool:
    """Send password reset code email using Resend"""
    if not RESEND_AVAILABLE or not RESEND_API_KEY:
        logger.warning("Resend not configured. Password reset email not sent.")
        return False

    html_content = get_password_reset_email_html(user_name, reset_code)

    params = {
        "from": SENDER_EMAIL,
        "to": [email],
        "subject": "Código de Redefinição - RH grupo Lisbonb",
        "html": html_content
    }

    try:
        email_response = await asyncio.to_thread(resend.Emails.send, params)
        logger.info(f"Password reset code email sent to {email}, ID: {email_response.get('id')}")
        return True
    except Exception as e:
        logger.error(f"Failed to send password reset email: {str(e)}")
        return False

def get_leave_request_email_html(employee_name: str, type_label: str, start_date: str, end_date: str, reason: str) -> str:
    """Template HTML do email de novo pedido de férias/ausência."""
    reason_html = f'<p style="margin:8px 0 0;"><strong>Motivo:</strong> {reason}</p>' if reason else ""
    return f"""
    <div style="font-family: Arial, Helvetica, sans-serif; max-width: 560px; margin: 0 auto; color: #1f2937;">
      <div style="background:#4f46e5; color:#fff; padding:20px; border-radius:8px 8px 0 0;">
        <h2 style="margin:0; font-size:18px;">Novo pedido de {type_label}</h2>
      </div>
      <div style="border:1px solid #e5e7eb; border-top:none; padding:20px; border-radius:0 0 8px 8px;">
        <p style="margin:0 0 12px;">O colaborador <strong>{employee_name}</strong> submeteu um pedido de {type_label}.</p>
        <p style="margin:4px 0;"><strong>Início:</strong> {start_date}</p>
        <p style="margin:4px 0;"><strong>Fim:</strong> {end_date}</p>
        {reason_html}
        <p style="margin:16px 0 0; font-size:13px; color:#6b7280;">
          Aceda ao RH grupo Lisbonb para aprovar ou recusar o pedido.
        </p>
      </div>
    </div>
    """

async def send_leave_request_email(to_emails: list, employee_name: str, type_label: str, start_date: str, end_date: str, reason: str = None) -> bool:
    """Avisar admins/gestores por email de um novo pedido de férias/ausência."""
    if not RESEND_AVAILABLE or not RESEND_API_KEY or not to_emails:
        return False

    params = {
        "from": SENDER_EMAIL,
        "to": to_emails,
        "subject": f"Novo pedido de {type_label} - {employee_name}",
        "html": get_leave_request_email_html(employee_name, type_label, start_date, end_date, reason or ""),
    }
    try:
        await asyncio.to_thread(resend.Emails.send, params)
        logger.info(f"Leave request email sent to {to_emails}")
        return True
    except Exception as e:
        logger.error(f"Failed to send leave request email: {str(e)}")
        return False

async def notify_managers_of_leave_request(employee_name: str, leave_type: str, start_date: str, end_date: str, reason: str = None):
    """Envia o email a todos os admins/gestores. Falha em silêncio (não bloqueia o pedido)."""
    try:
        managers = await db.users.find(
            {"role": {"$in": MANAGER_ROLES}},
            {"_id": 0, "email": 1}
        ).to_list(100)
        emails = [m["email"] for m in managers if m.get("email")]
        if not emails:
            return
        type_label = "férias" if leave_type == "ferias" else "ausência"
        await send_leave_request_email(emails, employee_name, type_label, start_date, end_date, reason)
    except Exception as e:
        logger.error(f"Erro ao notificar gestores do pedido de ausência: {str(e)}")

def get_leave_decision_email_html(employee_name: str, status: str, type_label: str, start_date: str, end_date: str, admin_response: str) -> str:
    """Template do email de decisão (aprovado/recusado) para o colaborador."""
    approved = status == "aprovado"
    color = "#0F9D70" if approved else "#D64545"
    chip = "Aprovado" if approved else "Recusado"
    note_html = f'<p style="margin:14px 0 0;"><strong>Resposta da administração:</strong> {admin_response}</p>' if admin_response else ""
    return f"""
    <div style="font-family: Arial, Helvetica, sans-serif; max-width: 560px; margin: 0 auto; color: #1f2937;">
      <div style="background:#1366F0; color:#fff; padding:20px; border-radius:8px 8px 0 0;">
        <h2 style="margin:0; font-size:18px;">RH grupo Lisbonb</h2>
      </div>
      <div style="border:1px solid #e5e7eb; border-top:none; padding:22px; border-radius:0 0 8px 8px;">
        <p style="margin:0 0 14px;">Olá {employee_name},</p>
        <p style="margin:0 0 14px;">O seu pedido de <strong>{type_label}</strong> foi:</p>
        <div style="display:inline-block; background:{color}; color:#fff; font-weight:bold; padding:8px 18px; border-radius:20px;">{chip}</div>
        <p style="margin:18px 0 4px;"><strong>Período:</strong> {start_date} a {end_date}</p>
        {note_html}
        <p style="margin:18px 0 0; font-size:13px; color:#6b7280;">Pode consultar os detalhes no sistema RH grupo Lisbonb.</p>
      </div>
    </div>
    """

async def notify_employee_of_leave_decision(employee_email: str, employee_name: str, status: str, type_label: str, start_date: str, end_date: str, admin_response: str = None):
    """Avisa o colaborador por email da decisão do seu pedido. Falha em silêncio."""
    if not RESEND_AVAILABLE or not RESEND_API_KEY or not employee_email:
        return
    try:
        params = {
            "from": SENDER_EMAIL,
            "to": [employee_email],
            "subject": f"O seu pedido de {type_label} foi {status}",
            "html": get_leave_decision_email_html(employee_name, status, type_label, start_date, end_date, admin_response or ""),
        }
        await asyncio.to_thread(resend.Emails.send, params)
        logger.info(f"Leave decision email sent to {employee_email}")
    except Exception as e:
        logger.error(f"Failed to send leave decision email: {str(e)}")

# ==================== MODELS ====================

class UserCreate(BaseModel):
    email: EmailStr
    password: str
    name: str
    role: str = "colaborador"

    @field_validator('password')
    @classmethod
    def validate_password(cls, v):
        is_valid, message = validate_password_strength(v)
        if not is_valid:
            raise ValueError(message)
        return v

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class UserResponse(BaseModel):
    id: str
    email: str
    name: str
    role: str
    employee_id: Optional[str] = None
    must_change_password: bool = False
    is_master_admin: bool = False

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

    @field_validator('new_password')
    @classmethod
    def validate_new_password(cls, v):
        is_valid, message = validate_password_strength(v)
        if not is_valid:
            raise ValueError(message)
        return v

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ResetPasswordCodeRequest(BaseModel):
    email: EmailStr
    code: str
    new_password: str

    @field_validator('code')
    @classmethod
    def validate_code(cls, v):
        code = v.strip()
        if not re.fullmatch(r"\d{6}", code):
            raise ValueError("O código deve ter 6 dígitos")
        return code

    @field_validator('new_password')
    @classmethod
    def validate_new_password(cls, v):
        is_valid, message = validate_password_strength(v)
        if not is_valid:
            raise ValueError(message)
        return v

class VerifyResetCodeRequest(BaseModel):
    email: EmailStr
    code: str

    @field_validator('code')
    @classmethod
    def validate_code(cls, v):
        code = v.strip()
        if not re.fullmatch(r"\d{6}", code):
            raise ValueError("O código deve ter 6 dígitos")
        return code

class CompanyCreate(BaseModel):
    name: str
    description: Optional[str] = None

class CompanyResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    created_at: str

class LocationCreate(BaseModel):
    name: str
    company_id: str
    address: Optional[str] = None
    # Cerca geográfica (opcional): posição do local e raio em metros.
    # Se geofence_radius estiver definido (>0), o ponto só é aceite dentro do raio.
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    geofence_radius: Optional[int] = None

class LocationResponse(BaseModel):
    id: str
    name: str
    company_id: str
    company_name: Optional[str] = None
    address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    geofence_radius: Optional[int] = None

class EmployeeCreate(BaseModel):
    name: str
    email: EmailStr
    password: str
    company_id: str
    location_id: Optional[str] = None  # opcional: colaboradores sem local físico
    position: str
    contract_type: str
    start_date: str
    vacation_days: int = 22
    observations: Optional[str] = None
    # Isento de cerca geográfica (ex.: trabalha em vários locais).
    # Se True, pode bater ponto de qualquer lugar (a localização é só registada).
    geofence_exempt: bool = False
    # Dados pessoais (o admin pode preencher; o colaborador também os edita)
    phone: Optional[str] = None
    address: Optional[str] = None
    birth_date: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None
    photo: Optional[str] = None

    @field_validator('password')
    @classmethod
    def validate_password(cls, v):
        is_valid, message = validate_password_strength(v)
        if not is_valid:
            raise ValueError(message)
        return v

class EmployeeUpdate(BaseModel):
    name: Optional[str] = None
    company_id: Optional[str] = None
    location_id: Optional[str] = None
    position: Optional[str] = None
    contract_type: Optional[str] = None
    start_date: Optional[str] = None
    vacation_days: Optional[int] = None
    observations: Optional[str] = None
    geofence_exempt: Optional[bool] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    birth_date: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None
    photo: Optional[str] = None

class EmployeeResponse(BaseModel):
    id: str
    user_id: str
    name: str
    email: str
    company_id: str
    company_name: Optional[str] = None
    location_id: Optional[str] = None
    location_name: Optional[str] = None
    position: str
    contract_type: str
    start_date: str
    vacation_days: int
    vacation_days_used: int = 0
    vacation_days_available: int = 0
    observations: Optional[str] = None
    geofence_exempt: bool = False
    # Dados de perfil (editáveis pelo próprio colaborador)
    phone: Optional[str] = None
    address: Optional[str] = None
    birth_date: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None
    photo: Optional[str] = None  # imagem em data URL (base64)
    created_at: str

class SelfProfileUpdate(BaseModel):
    """Campos que o próprio colaborador pode editar no seu perfil."""
    phone: Optional[str] = None
    address: Optional[str] = None
    birth_date: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None
    photo: Optional[str] = None

class TimeRecordCreate(BaseModel):
    record_type: str  # entrada or saida
    # Geolocalização (opcional - o browser pode negar)
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    accuracy: Optional[float] = None  # precisão em metros

class TimeRecordCorrection(BaseModel):
    time: str
    justification: str

class TimeRecordResponse(BaseModel):
    id: str
    employee_id: str
    employee_name: Optional[str] = None
    record_type: str
    time: str
    corrected: bool = False
    correction_history: List[dict] = []
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    accuracy: Optional[float] = None

class AdminLeaveCreate(BaseModel):
    user_id: str = Field(alias="userId")
    leave_type: str = Field(alias="type")
    start_date: str = Field(alias="startDate")
    end_date: str = Field(alias="endDate")
    reason: Optional[str] = None
    is_paid: bool = Field(alias="isPaid")

    model_config = {"populate_by_name": True}

    @field_validator('leave_type')
    @classmethod
    def validate_leave_type(cls, v):
        if v not in ["ferias", "ausencia"]:
            raise ValueError("Tipo inválido. Use 'ferias' ou 'ausencia'")
        return v

class WorkScheduleTemplateCreate(BaseModel):
    name: str
    work_days: List[int] = Field(alias="workDays")

    model_config = {"populate_by_name": True}

    @field_validator('work_days')
    @classmethod
    def validate_work_days(cls, v):
        if not v:
            raise ValueError("Selecione pelo menos um dia de trabalho")
        if any(day not in range(0, 7) for day in v):
            raise ValueError("Dias de trabalho inválidos")
        if len(set(v)) != len(v):
            raise ValueError("Dias de trabalho duplicados")
        return v

class WorkScheduleTemplateResponse(BaseModel):
    id: str
    name: str
    work_days: List[int]
    created_at: str

class WorkScheduleAssignmentCreate(BaseModel):
    employee_id: str = Field(alias="employeeId")
    template_id: str = Field(alias="templateId")
    start_date: str = Field(alias="startDate")
    end_date: Optional[str] = Field(default=None, alias="endDate")

    model_config = {"populate_by_name": True}

    @field_validator('start_date', 'end_date')
    @classmethod
    def validate_dates(cls, v):
        if v is None:
            return v
        try:
            datetime.fromisoformat(v)
        except ValueError:
            raise ValueError("Datas inválidas. Use o formato AAAA-MM-DD")
        return v

class WorkScheduleAssignmentResponse(BaseModel):
    id: str
    employee_id: str
    employee_name: Optional[str] = None
    template_id: str
    template_name: Optional[str] = None
    work_days: List[int] = []
    start_date: str
    end_date: Optional[str] = None
    created_at: str

class LeaveRequestCreate(BaseModel):
    leave_type: str  # ferias, falta, doenca, folga
    start_date: str
    end_date: str
    observation: Optional[str] = None

class LeaveRequestResponse(BaseModel):
    id: str
    employee_id: str
    employee_name: Optional[str] = None
    leave_type: str
    start_date: str
    end_date: str
    status: str  # pendente, aprovado, recusado
    observation: Optional[str] = None
    document_id: Optional[str] = None
    admin_response: Optional[str] = None
    created_by: Optional[str] = None
    is_paid: Optional[bool] = None
    counted_days: Optional[int] = None
    audit_log: Optional[List[dict]] = None
    created_at: str

class FolderCreate(BaseModel):
    name: str
    employee_id: str
    allow_employee_upload: bool = False

class FolderResponse(BaseModel):
    id: str
    name: str
    employee_id: str
    allow_employee_upload: bool
    created_at: str

class DocumentResponse(BaseModel):
    id: str
    name: str
    folder_id: str
    folder_name: Optional[str] = None
    employee_id: str
    uploaded_by: str
    uploaded_by_name: Optional[str] = None
    file_path: str
    created_at: str

class NotificationResponse(BaseModel):
    id: str
    user_id: str
    title: str
    message: str
    read: bool
    created_at: str

class DashboardStats(BaseModel):
    total_employees: int
    total_companies: int
    pending_requests: int
    today_records: int
    employees_by_company: List[dict]
    recent_requests: List[dict]

def build_audit_entry(action: str, actor: dict) -> dict:
    return {
        "action": action,
        "actor_id": actor.get("user_id"),
        "actor_name": actor.get("name"),
        "actor_role": actor.get("role"),
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

# ==================== VACATION CALCULATION ====================

def _easter_sunday(year: int) -> date:
    """Domingo de Páscoa (algoritmo anónimo gregoriano)."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)

_pt_holiday_cache: dict = {}

def get_pt_holidays(year: int) -> set:
    """Feriados nacionais obrigatórios de Portugal para o ano indicado."""
    if year in _pt_holiday_cache:
        return _pt_holiday_cache[year]
    easter = _easter_sunday(year)
    holidays = {
        date(year, 1, 1),    # Ano Novo
        date(year, 4, 25),   # Dia da Liberdade
        date(year, 5, 1),    # Dia do Trabalhador
        date(year, 6, 10),   # Dia de Portugal
        date(year, 8, 15),   # Assunção de Nossa Senhora
        date(year, 10, 5),   # Implantação da República
        date(year, 11, 1),   # Todos os Santos
        date(year, 12, 1),   # Restauração da Independência
        date(year, 12, 8),   # Imaculada Conceição
        date(year, 12, 25),  # Natal
        easter - timedelta(days=2),   # Sexta-feira Santa
        easter,                       # Páscoa
        easter + timedelta(days=60),  # Corpo de Deus
    }
    _pt_holiday_cache[year] = holidays
    return holidays

def find_schedule_assignment(assignments: list[dict], target_date: date):
    for assignment in assignments:
        start_dt = datetime.fromisoformat(assignment["start_date"]).date()
        end_raw = assignment.get("end_date")
        end_dt = datetime.fromisoformat(end_raw).date() if end_raw else None
        if target_date >= start_dt and (end_dt is None or target_date <= end_dt):
            return assignment
    return None

async def calculate_leave_counted_days(employee_id: str, start_date: str, end_date: str) -> int:
    """Count leave days based on work schedule."""
    start_dt = datetime.fromisoformat(start_date).date()
    end_dt = datetime.fromisoformat(end_date).date()

    if start_dt > end_dt:
        return 0

    assignments = await db.work_schedule_assignments.find(
        {"employee_id": employee_id},
        {"_id": 0}
    ).sort("start_date", 1).to_list(200)

    for assignment in assignments:
        if not assignment.get("work_days"):
            template = await db.work_schedule_templates.find_one(
                {"id": assignment.get("template_id")},
                {"_id": 0, "work_days": 1}
            )
            if template:
                assignment["work_days"] = template.get("work_days", [])

    total_days = 0
    current_date = start_dt
    while current_date <= end_dt:
        # Feriados nunca contam
        if current_date in get_pt_holidays(current_date.year):
            current_date += timedelta(days=1)
            continue

        assignment = find_schedule_assignment(assignments, current_date)
        if assignment:
            # Com escala: só contam os dias de trabalho (folgas não contam)
            work_days = assignment.get("work_days", [])
            if current_date.weekday() in work_days:
                total_days += 1
        else:
            # Sem escala: por defeito, só dias úteis (Seg-Sex); fim de semana não conta
            if current_date.weekday() < 5:
                total_days += 1
        current_date += timedelta(days=1)

    return total_days

async def calculate_vacation_days_used(employee_id: str) -> int:
    """Calculate the number of vacation days used by an employee in the current year"""
    current_year = datetime.now(timezone.utc).year
    year_start = f"{current_year}-01-01"
    year_end = f"{current_year}-12-31"

    # Find all approved vacation requests for the current year
    vacation_requests = await db.leave_requests.find({
        "employee_id": employee_id,
        "leave_type": "ferias",
        "status": "aprovado",
        "$or": [
            {"start_date": {"$gte": year_start, "$lte": year_end}},
            {"end_date": {"$gte": year_start, "$lte": year_end}},
            {"$and": [{"start_date": {"$lte": year_start}}, {"end_date": {"$gte": year_end}}]}
        ]
    }, {"_id": 0}).to_list(1000)

    total_days = 0
    for request in vacation_requests:
        start = datetime.fromisoformat(request["start_date"])
        end = datetime.fromisoformat(request["end_date"])

        # Adjust dates to current year boundaries
        year_start_date = datetime(current_year, 1, 1)
        year_end_date = datetime(current_year, 12, 31)

        effective_start = max(start, year_start_date)
        effective_end = min(end, year_end_date)

        if effective_start <= effective_end:
            counted = await calculate_leave_counted_days(
                employee_id,
                effective_start.date().isoformat(),
                effective_end.date().isoformat()
            )
            total_days += counted

    return total_days

# ==================== AUTH UTILITIES ====================

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Get current user from JWT token"""
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expirado")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Token inválido")

async def admin_required(current_user: dict = Depends(get_current_user)):
    """Acesso operacional completo: admin OU gestor (gerente).

    O gestor/contabilista pode fazer tudo. A gestão de outros gestores/admins
    continua exclusiva do admin master (verificação por email nos /admins).
    """
    if current_user.get("role") not in MANAGER_ROLES:
        raise HTTPException(status_code=403, detail="Acesso negado. Apenas administradores ou gestores.")
    user_doc = await db.users.find_one({"id": current_user.get("user_id")}, {"_id": 0, "name": 1, "role": 1})
    current_user["name"] = user_doc.get("name") if user_doc else current_user.get("email")
    return current_user

async def admin_manager_required(current_user: dict = Depends(get_current_user)):
    """Require admin or manager role"""
    if current_user.get("role") not in MANAGER_ROLES:
        raise HTTPException(status_code=403, detail="Acesso negado. Apenas administradores ou gestores.")
    user_doc = await db.users.find_one({"id": current_user.get("user_id")}, {"_id": 0, "name": 1, "role": 1})
    current_user["name"] = user_doc.get("name") if user_doc else current_user.get("email")
    return current_user

async def ensure_master_admin_exists():
    """Garante que o admin master existe.

    Password vem de ADMIN_PASSWORD (texto simples, encriptada aqui) ou, em
    alternativa, de ADMIN_PASSWORD_HASH (hash já pronto). Usar ADMIN_PASSWORD
    evita problemas com o '$' do hash em ficheiros .env / docker-compose.
    Se o admin já existir e ADMIN_PASSWORD estiver definido, a password é
    atualizada (o .env é a fonte de verdade para o admin master).
    """
    admin_password = os.environ.get('ADMIN_PASSWORD')
    password_hash = hash_password(admin_password) if admin_password else MASTER_ADMIN_PASSWORD_HASH

    if not password_hash:
        logger.warning("Nem ADMIN_PASSWORD nem ADMIN_PASSWORD_HASH configurados. Admin master não criado.")
        return

    existing = await db.users.find_one({"email": MASTER_ADMIN_EMAIL})
    if not existing:
        admin_doc = {
            "id": str(uuid.uuid4()),
            "email": MASTER_ADMIN_EMAIL,
            "password": password_hash,
            "name": "Administrador Principal",
            "role": "admin",
            "employee_id": None,
            "must_change_password": False,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        await db.users.insert_one(admin_doc)
        logger.info(f"Master admin created: {MASTER_ADMIN_EMAIL}")
    elif admin_password:
        # Repara/atualiza a password do admin master a partir do .env
        await db.users.update_one(
            {"email": MASTER_ADMIN_EMAIL},
            {"$set": {"password": password_hash, "must_change_password": False}}
        )
        logger.info(f"Master admin password atualizada: {MASTER_ADMIN_EMAIL}")

# ==================== AUTH ROUTES ====================

@api_router.post("/auth/login")
async def login(credentials: UserLogin):
    """Authenticate user and return JWT token"""
    user = await db.users.find_one({"email": credentials.email}, {"_id": 0})
    if not user or not verify_password(credentials.password, user["password"]):
        raise HTTPException(status_code=401, detail="Credenciais inválidas")
    
    must_change_password = user.get("must_change_password", False)
    
    token = create_token(
        user["id"], 
        user["email"], 
        user["role"], 
        user.get("employee_id"),
        must_change_password
    )
    
    return {
        "token": token,
        "user": {
            "id": user["id"],
            "email": user["email"],
            "name": user["name"],
            "role": user["role"],
            "employee_id": user.get("employee_id"),
            "must_change_password": must_change_password,
            "is_master_admin": user["email"] == MASTER_ADMIN_EMAIL
        }
    }

@api_router.get("/auth/me", response_model=UserResponse)
async def get_me(current_user: dict = Depends(get_current_user)):
    """Get current user information"""
    user = await db.users.find_one({"id": current_user["user_id"]}, {"_id": 0, "password": 0})
    if not user:
        raise HTTPException(status_code=404, detail="Utilizador não encontrado")
    user["is_master_admin"] = user.get("email") == MASTER_ADMIN_EMAIL
    return UserResponse(**user)

@api_router.post("/auth/change-password")
async def change_password(request: ChangePasswordRequest, current_user: dict = Depends(get_current_user)):
    """Change user password"""
    user = await db.users.find_one({"id": current_user["user_id"]}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=404, detail="Utilizador não encontrado")
    
    # Verify current password
    if not verify_password(request.current_password, user["password"]):
        raise HTTPException(status_code=400, detail="Palavra-passe atual incorreta")
    
    # Check if new password is different from current
    if verify_password(request.new_password, user["password"]):
        raise HTTPException(status_code=400, detail="A nova palavra-passe deve ser diferente da atual")
    
    # Update password and set must_change_password to False
    new_password_hash = hash_password(request.new_password)
    await db.users.update_one(
        {"id": current_user["user_id"]},
        {"$set": {"password": new_password_hash, "must_change_password": False}}
    )
    
    # Generate new token with must_change_password = False
    token = create_token(
        user["id"],
        user["email"],
        user["role"],
        user.get("employee_id"),
        False
    )
    
    return {
        "message": "Palavra-passe alterada com sucesso",
        "token": token
    }

# ==================== PASSWORD RESET ENDPOINTS ====================

@api_router.post("/auth/forgot-password")
async def forgot_password(request: ForgotPasswordRequest):
    """
    Request password reset. Sends email with 6-digit code if user exists.
    Always returns success to prevent email enumeration attacks.
    """
    success_message = {
        "message": "Se o email existir no sistema, receberá um código de 6 dígitos para redefinir a palavra-passe."
    }

    normalized_email = request.email.lower().strip()

    logger.info("=== FORGOT PASSWORD DEBUG ===")
    logger.info(f"Email RECEBIDO (raw): '{request.email}'")
    logger.info(f"Email NORMALIZADO: '{normalized_email}'")

    user = await db.users.find_one(
        {"email": {"$regex": f"^{re.escape(normalized_email)}$", "$options": "i"}},
        {"_id": 0}
    )

    if not user:
        user = await db.users.find_one({"email": normalized_email}, {"_id": 0})

    all_users = await db.users.find({}, {"_id": 0, "email": 1, "id": 1}).to_list(100)
    logger.info(f"Total de usuários no banco: {len(all_users)}")
    for u in all_users:
        match = u.get('email', '').lower().strip() == normalized_email
        logger.info(f"  - '{u.get('email')}' | ID: {u.get('id')[:8]}... | MATCH: {match}")

    if not user:
        logger.warning(f"Usuário NÃO ENCONTRADO para email: '{normalized_email}'")
        logger.info("=== END FORGOT PASSWORD DEBUG ===")
        return success_message

    logger.info(f"Usuário ENCONTRADO: {user.get('email')} | ID: {user.get('id')}")
    logger.info(f"Nome: {user.get('name')}")

    reset_code = generate_reset_code()
    code_hash = hash_reset_token(reset_code)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=RESET_TOKEN_EXPIRATION_HOURS)

    logger.info("Código de redefinição gerado e preparado para envio.")

    update_result = await db.users.update_one(
        {"id": user["id"]},
        {
            "$set": {
                "reset_password_token": code_hash,
                "reset_password_expires": expires_at.isoformat()
            }
        }
    )

    logger.info(f"Update result: matched={update_result.matched_count}, modified={update_result.modified_count}")

    saved_user = await db.users.find_one({"id": user["id"]}, {"_id": 0, "email": 1, "reset_password_token": 1})
    logger.info("Verificação após salvar:")
    logger.info(f"  Email do usuário salvo: {saved_user.get('email')}")
    logger.info(f"  Token HASH no banco: {saved_user.get('reset_password_token')}")
    logger.info(f"  Hashes IGUAIS: {saved_user.get('reset_password_token') == code_hash}")

    email_sent = await send_password_reset_email(
        email=user["email"],
        user_name=user["name"],
        reset_code=reset_code
    )

    if email_sent:
        logger.info(f"Email ENVIADO com sucesso para: {user['email']}")
    else:
        logger.warning(f"FALHA ao enviar email para: {user['email']}")

    logger.info("=== END FORGOT PASSWORD DEBUG ===")

    return success_message

@api_router.post("/auth/reset-password")
async def reset_password(request: ResetPasswordCodeRequest):
    """
    Reset password using the code received via email.
    Code must be valid and not expired.
    """
    logger.info("=== RESET PASSWORD DEBUG ===")

    normalized_email = request.email.lower().strip()
    code = request.code.strip()

    logger.info(f"Email NORMALIZADO: '{normalized_email}'")
    logger.info(f"Código RECEBIDO LENGTH: {len(code)}")

    code_hash = hash_reset_token(code)

    user = await db.users.find_one(
        {"email": {"$regex": f"^{re.escape(normalized_email)}$", "$options": "i"}, "reset_password_token": code_hash},
        {"_id": 0}
    )

    if not user:
        user = await db.users.find_one(
            {"email": normalized_email, "reset_password_token": code_hash},
            {"_id": 0}
        )

    if not user:
        logger.warning("Código NÃO encontrado para o email informado!")
        logger.info("=== END RESET PASSWORD DEBUG ===")
        raise HTTPException(
            status_code=400,
            detail="Código inválido ou expirado. Por favor, solicite um novo código."
        )

    expires_at = user.get("reset_password_expires")
    if expires_at:
        expires_datetime = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
        if datetime.now(timezone.utc) > expires_datetime:
            await db.users.update_one(
                {"id": user["id"]},
                {"$unset": {"reset_password_token": "", "reset_password_expires": ""}}
            )
            logger.warning("Código EXPIRADO!")
            logger.info("=== END RESET PASSWORD DEBUG ===")
            raise HTTPException(
                status_code=400,
                detail="Código expirado. Por favor, solicite um novo código."
            )

    new_password_hash = hash_password(request.new_password)

    await db.users.update_one(
        {"id": user["id"]},
        {
            "$set": {
                "password": new_password_hash,
                "must_change_password": False
            },
            "$unset": {
                "reset_password_token": "",
                "reset_password_expires": ""
            }
        }
    )

    logger.info(f"Password successfully reset for user {user['email']}")
    logger.info("=== END RESET PASSWORD DEBUG ===")

    return {
        "message": "Palavra-passe redefinida com sucesso. Pode agora fazer login com a nova palavra-passe."
    }

@api_router.post("/auth/verify-reset-code")
async def verify_reset_code(request: VerifyResetCodeRequest):
    """
    Verify if a password reset code is valid (for frontend validation before showing form).
    """
    logger.info("=== VERIFY CODE DEBUG ===")

    normalized_email = request.email.lower().strip()
    code = request.code.strip()

    logger.info(f"Email NORMALIZADO: '{normalized_email}'")
    logger.info(f"Código RECEBIDO LENGTH: {len(code)}")

    code_hash = hash_reset_token(code)

    user = await db.users.find_one(
        {"email": {"$regex": f"^{re.escape(normalized_email)}$", "$options": "i"}, "reset_password_token": code_hash},
        {"_id": 0}
    )

    if not user:
        user = await db.users.find_one(
            {"email": normalized_email, "reset_password_token": code_hash},
            {"_id": 0}
        )

    if not user:
        logger.warning("Código NÃO encontrado para o email informado!")
        logger.info("=== END VERIFY CODE DEBUG ===")
        raise HTTPException(status_code=400, detail="Código inválido")

    expires_at = user.get("reset_password_expires")
    if expires_at:
        expires_datetime = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
        if datetime.now(timezone.utc) > expires_datetime:
            await db.users.update_one(
                {"id": user["id"]},
                {"$unset": {"reset_password_token": "", "reset_password_expires": ""}}
            )
            logger.warning("Código EXPIRADO!")
            logger.info("=== END VERIFY CODE DEBUG ===")
            raise HTTPException(status_code=400, detail="Código expirado")

    logger.info("=== END VERIFY CODE DEBUG ===")
    return {"valid": True, "email": user["email"]}

# ==================== ADMIN/MANAGER CREATION ====================

class AdminCreate(BaseModel):
    email: EmailStr
    password: str
    name: str
    role: str = "admin"  # admin or gerente

    @field_validator('password')
    @classmethod
    def validate_password(cls, v):
        is_valid, message = validate_password_strength(v)
        if not is_valid:
            raise ValueError(message)
        return v

    @field_validator('role')
    @classmethod
    def validate_role(cls, v):
        if v not in MANAGER_ROLES:
            raise ValueError("Função inválida")
        return v

class AdminResponse(BaseModel):
    id: str
    email: str
    name: str
    role: str
    created_at: str

@api_router.post("/admins", response_model=AdminResponse)
async def create_admin(admin: AdminCreate, current_user: dict = Depends(admin_required)):
    """Create a new admin or manager (admin only). Must change password on first login."""
    # Only master admin can create other admins
    user = await db.users.find_one({"id": current_user["user_id"]}, {"_id": 0})
    if user["email"] != MASTER_ADMIN_EMAIL:
        raise HTTPException(status_code=403, detail="Apenas o administrador master pode criar outros administradores")
    
    # Check if email exists
    existing = await db.users.find_one({"email": admin.email})
    if existing:
        raise HTTPException(status_code=400, detail="Email já registado")
    
    # Create admin/manager with must_change_password = True
    user_id = str(uuid.uuid4())
    user_doc = {
        "id": user_id,
        "email": admin.email,
        "password": hash_password(admin.password),
        "name": admin.name,
        "role": admin.role,
        "employee_id": None,
        "must_change_password": True,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.users.insert_one(user_doc)
    
    logger.info(f"New {admin.role} created: {admin.email}")
    
    return AdminResponse(
        id=user_id,
        email=admin.email,
        name=admin.name,
        role=admin.role,
        created_at=user_doc["created_at"]
    )

@api_router.get("/admins", response_model=List[AdminResponse])
async def get_admins(current_user: dict = Depends(admin_required)):
    """Get all admins and managers (master admin only)"""
    user = await db.users.find_one({"id": current_user["user_id"]}, {"_id": 0})
    if user["email"] != MASTER_ADMIN_EMAIL:
        raise HTTPException(status_code=403, detail="Apenas o administrador master pode ver administradores")
    
    admins = await db.users.find(
        {"role": {"$in": MANAGER_ROLES}, "email": {"$ne": MASTER_ADMIN_EMAIL}},
        {"_id": 0, "password": 0}
    ).to_list(100)
    
    return [AdminResponse(**a) for a in admins]

@api_router.delete("/admins/{admin_id}")
async def delete_admin(admin_id: str, current_user: dict = Depends(admin_required)):
    """Delete an admin or manager (master admin only)"""
    user = await db.users.find_one({"id": current_user["user_id"]}, {"_id": 0})
    if user["email"] != MASTER_ADMIN_EMAIL:
        raise HTTPException(status_code=403, detail="Apenas o administrador master pode eliminar administradores")
    
    admin = await db.users.find_one({"id": admin_id}, {"_id": 0})
    if not admin:
        raise HTTPException(status_code=404, detail="Administrador não encontrado")
    
    if admin["email"] == MASTER_ADMIN_EMAIL:
        raise HTTPException(status_code=400, detail="Não é possível eliminar o administrador master")
    
    await db.users.delete_one({"id": admin_id})
    return {"message": f"Administrador {admin['name']} eliminado com sucesso"}

# ==================== COMPANY ROUTES ====================

@api_router.post("/companies", response_model=CompanyResponse)
async def create_company(company: CompanyCreate, current_user: dict = Depends(admin_required)):
    company_id = str(uuid.uuid4())
    company_doc = {
        "id": company_id,
        "name": company.name,
        "description": company.description,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.companies.insert_one(company_doc)
    return CompanyResponse(**company_doc)

@api_router.get("/companies", response_model=List[CompanyResponse])
async def get_companies(current_user: dict = Depends(get_current_user)):
    companies = await db.companies.find({}, {"_id": 0}).to_list(100)
    return [CompanyResponse(**c) for c in companies]

@api_router.get("/companies/{company_id}", response_model=CompanyResponse)
async def get_company(company_id: str, current_user: dict = Depends(get_current_user)):
    company = await db.companies.find_one({"id": company_id}, {"_id": 0})
    if not company:
        raise HTTPException(status_code=404, detail="Empresa não encontrada")
    return CompanyResponse(**company)

@api_router.put("/companies/{company_id}", response_model=CompanyResponse)
async def update_company(company_id: str, company: CompanyCreate, current_user: dict = Depends(admin_required)):
    result = await db.companies.update_one(
        {"id": company_id},
        {"$set": {"name": company.name, "description": company.description}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Empresa não encontrada")
    updated = await db.companies.find_one({"id": company_id}, {"_id": 0})
    return CompanyResponse(**updated)

@api_router.delete("/companies/{company_id}")
async def delete_company(company_id: str, current_user: dict = Depends(admin_required)):
    # Check if company has employees
    employee_count = await db.employees.count_documents({"company_id": company_id})
    if employee_count > 0:
        raise HTTPException(status_code=400, detail="Não é possível eliminar empresa com colaboradores associados")
    
    result = await db.companies.delete_one({"id": company_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Empresa não encontrada")
    
    # Delete associated locations
    await db.locations.delete_many({"company_id": company_id})
    return {"message": "Empresa eliminada com sucesso"}

# ==================== LOCATION ROUTES ====================

@api_router.post("/locations", response_model=LocationResponse)
async def create_location(location: LocationCreate, current_user: dict = Depends(admin_required)):
    # Verify company exists
    company = await db.companies.find_one({"id": location.company_id}, {"_id": 0})
    if not company:
        raise HTTPException(status_code=404, detail="Empresa não encontrada")
    
    location_id = str(uuid.uuid4())
    location_doc = {
        "id": location_id,
        "name": location.name,
        "company_id": location.company_id,
        "address": location.address,
        "latitude": location.latitude,
        "longitude": location.longitude,
        "geofence_radius": location.geofence_radius,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.locations.insert_one(location_doc)
    return LocationResponse(**location_doc, company_name=company["name"])

@api_router.get("/locations", response_model=List[LocationResponse])
async def get_locations(company_id: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    query = {}
    if company_id:
        query["company_id"] = company_id
    
    locations = await db.locations.find(query, {"_id": 0}).to_list(100)
    
    # Get company names
    for loc in locations:
        company = await db.companies.find_one({"id": loc["company_id"]}, {"_id": 0})
        loc["company_name"] = company["name"] if company else None
    
    return [LocationResponse(**loc) for loc in locations]

@api_router.put("/locations/{location_id}", response_model=LocationResponse)
async def update_location(location_id: str, location: LocationCreate, current_user: dict = Depends(admin_required)):
    result = await db.locations.update_one(
        {"id": location_id},
        {"$set": {
            "name": location.name,
            "company_id": location.company_id,
            "address": location.address,
            "latitude": location.latitude,
            "longitude": location.longitude,
            "geofence_radius": location.geofence_radius,
        }}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Local não encontrado")
    updated = await db.locations.find_one({"id": location_id}, {"_id": 0})
    company = await db.companies.find_one({"id": updated["company_id"]}, {"_id": 0})
    return LocationResponse(**updated, company_name=company["name"] if company else None)

@api_router.delete("/locations/{location_id}")
async def delete_location(location_id: str, current_user: dict = Depends(admin_required)):
    # Check if location has employees
    employee_count = await db.employees.count_documents({"location_id": location_id})
    if employee_count > 0:
        raise HTTPException(status_code=400, detail="Não é possível eliminar local com colaboradores associados")
    
    result = await db.locations.delete_one({"id": location_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Local não encontrado")
    return {"message": "Local eliminado com sucesso"}

# ==================== EMPLOYEE ROUTES ====================

@api_router.post("/employees", response_model=EmployeeResponse)
async def create_employee(employee: EmployeeCreate, current_user: dict = Depends(admin_required)):
    """Create employee with temporary password (must_change_password = true)"""
    # Check if email exists
    existing = await db.users.find_one({"email": employee.email})
    if existing:
        raise HTTPException(status_code=400, detail="Email já registado")
    
    # Verify company and location
    company = await db.companies.find_one({"id": employee.company_id}, {"_id": 0})
    if not company:
        raise HTTPException(status_code=404, detail="Empresa não encontrada")
    
    if employee.location_id:
        location = await db.locations.find_one({"id": employee.location_id}, {"_id": 0})
        if not location:
            raise HTTPException(status_code=404, detail="Local não encontrado")

    validate_photo_data_url(employee.photo)

    # Create user account with must_change_password = True (temporary password)
    user_id = str(uuid.uuid4())
    employee_id = str(uuid.uuid4())
    
    user_doc = {
        "id": user_id,
        "email": employee.email,
        "password": hash_password(employee.password),
        "name": employee.name,
        "role": "colaborador",
        "employee_id": employee_id,
        "must_change_password": True,  # User must change password on first login
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.users.insert_one(user_doc)
    
    # Create employee record
    employee_doc = {
        "id": employee_id,
        "user_id": user_id,
        "name": employee.name,
        "email": employee.email,
        "company_id": employee.company_id,
        "location_id": employee.location_id,
        "position": employee.position,
        "contract_type": employee.contract_type,
        "start_date": employee.start_date,
        "vacation_days": employee.vacation_days,
        "observations": employee.observations,
        "geofence_exempt": employee.geofence_exempt,
        "phone": employee.phone,
        "address": employee.address,
        "birth_date": employee.birth_date,
        "emergency_contact_name": employee.emergency_contact_name,
        "emergency_contact_phone": employee.emergency_contact_phone,
        "photo": employee.photo,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.employees.insert_one(employee_doc)
    
    # Create default folders
    default_folders = [
        {"name": "Contrato", "allow_employee_upload": False},
        {"name": "Recibos de Vencimento", "allow_employee_upload": False},
        {"name": "Documentos Pessoais", "allow_employee_upload": True},
        {"name": "Justificações de Faltas", "allow_employee_upload": True},
        {"name": "Outros", "allow_employee_upload": True}
    ]
    
    for folder in default_folders:
        folder_doc = {
            "id": str(uuid.uuid4()),
            "name": folder["name"],
            "employee_id": employee_id,
            "allow_employee_upload": folder["allow_employee_upload"],
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        await db.folders.insert_one(folder_doc)
    
    # Create welcome notification with password change reminder
    notification_doc = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "title": "Bem-vindo!",
        "message": f"A sua conta foi criada com sucesso. Bem-vindo à {company['name']}! Por favor, altere a sua palavra-passe temporária no primeiro acesso.",
        "read": False,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.notifications.insert_one(notification_doc)
    
    return EmployeeResponse(
        **employee_doc,
        company_name=company["name"],
        location_name=location["name"]
    )

@api_router.get("/employees", response_model=List[EmployeeResponse])
async def get_employees(
    company_id: Optional[str] = None,
    location_id: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    query = {}
    if company_id:
        query["company_id"] = company_id
    if location_id:
        query["location_id"] = location_id
    
    # If colaborador, only return their own data
    if current_user.get("role") == "colaborador":
        query["id"] = current_user.get("employee_id")
    
    employees = await db.employees.find(query, {"_id": 0}).to_list(1000)

    # Get company and location names and calculate vacation days
    for emp in employees:
        company = await db.companies.find_one({"id": emp["company_id"]}, {"_id": 0})
        location = await db.locations.find_one({"id": emp["location_id"]}, {"_id": 0})
        emp["company_name"] = company["name"] if company else None
        emp["location_name"] = location["name"] if location else None
        
        # Calculate vacation days used and available
        vacation_used = await calculate_vacation_days_used(emp["id"])
        emp["vacation_days_used"] = vacation_used
        emp["vacation_days_available"] = emp["vacation_days"] - vacation_used
    
    return [EmployeeResponse(**e) for e in employees]

@api_router.get("/employees/{employee_id}", response_model=EmployeeResponse)
async def get_employee(employee_id: str, current_user: dict = Depends(get_current_user)):
    # Colaboradores can only see their own data
    if current_user.get("role") == "colaborador" and current_user.get("employee_id") != employee_id:
        raise HTTPException(status_code=403, detail="Acesso negado")
    
    employee = await db.employees.find_one({"id": employee_id}, {"_id": 0})
    if not employee:
        raise HTTPException(status_code=404, detail="Colaborador não encontrado")
    
    company = await db.companies.find_one({"id": employee["company_id"]}, {"_id": 0})
    location = await db.locations.find_one({"id": employee["location_id"]}, {"_id": 0})
    
    # Calculate vacation days used and available
    vacation_used = await calculate_vacation_days_used(employee_id)
    
    return EmployeeResponse(
        **employee,
        company_name=company["name"] if company else None,
        location_name=location["name"] if location else None,
        vacation_days_used=vacation_used,
        vacation_days_available=employee["vacation_days"] - vacation_used
    )

async def _build_employee_response(employee: dict) -> EmployeeResponse:
    company = await db.companies.find_one({"id": employee["company_id"]}, {"_id": 0})
    location = None
    if employee.get("location_id"):
        location = await db.locations.find_one({"id": employee["location_id"]}, {"_id": 0})
    vacation_used = await calculate_vacation_days_used(employee["id"])
    return EmployeeResponse(
        **employee,
        company_name=company["name"] if company else None,
        location_name=location["name"] if location else None,
        vacation_days_used=vacation_used,
        vacation_days_available=employee["vacation_days"] - vacation_used
    )

@api_router.get("/me/profile", response_model=EmployeeResponse)
async def get_my_profile(current_user: dict = Depends(get_current_user)):
    """Perfil do próprio colaborador (com foto e dados pessoais)."""
    employee_id = current_user.get("employee_id")
    if not employee_id:
        raise HTTPException(status_code=400, detail="Utilizador não associado a colaborador")
    employee = await db.employees.find_one({"id": employee_id}, {"_id": 0})
    if not employee:
        raise HTTPException(status_code=404, detail="Perfil não encontrado")
    return await _build_employee_response(employee)

@api_router.put("/me/profile", response_model=EmployeeResponse)
async def update_my_profile(profile: SelfProfileUpdate, current_user: dict = Depends(get_current_user)):
    """O colaborador atualiza os seus próprios dados (foto, contactos, etc.)."""
    employee_id = current_user.get("employee_id")
    if not employee_id:
        raise HTTPException(status_code=400, detail="Utilizador não associado a colaborador")

    update_data = {k: v for k, v in profile.model_dump().items() if v is not None}

    photo = update_data.get("photo")
    if photo:
        if not photo.startswith("data:image/"):
            raise HTTPException(status_code=400, detail="Formato de imagem inválido")
        if len(photo) > 4_000_000:  # ~3MB
            raise HTTPException(status_code=400, detail="Imagem demasiado grande (máx. ~3MB)")

    if update_data:
        await db.employees.update_one({"id": employee_id}, {"$set": update_data})

    employee = await db.employees.find_one({"id": employee_id}, {"_id": 0})
    return await _build_employee_response(employee)

@api_router.put("/employees/{employee_id}", response_model=EmployeeResponse)
async def update_employee(employee_id: str, employee: EmployeeUpdate, current_user: dict = Depends(admin_required)):
    update_data = {k: v for k, v in employee.model_dump().items() if v is not None}

    if not update_data:
        raise HTTPException(status_code=400, detail="Nenhum dado para atualizar")

    validate_photo_data_url(update_data.get("photo"))

    # Also update name in users collection if provided
    if "name" in update_data:
        emp = await db.employees.find_one({"id": employee_id}, {"_id": 0})
        if emp:
            await db.users.update_one({"id": emp["user_id"]}, {"$set": {"name": update_data["name"]}})
    
    result = await db.employees.update_one({"id": employee_id}, {"$set": update_data})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Colaborador não encontrado")
    
    updated = await db.employees.find_one({"id": employee_id}, {"_id": 0})
    company = await db.companies.find_one({"id": updated["company_id"]}, {"_id": 0})
    location = await db.locations.find_one({"id": updated["location_id"]}, {"_id": 0})
    
    return EmployeeResponse(
        **updated,
        company_name=company["name"] if company else None,
        location_name=location["name"] if location else None
    )

@api_router.delete("/employees/{employee_id}")
async def delete_employee(employee_id: str, current_user: dict = Depends(admin_required)):
    employee = await db.employees.find_one({"id": employee_id}, {"_id": 0})
    if not employee:
        raise HTTPException(status_code=404, detail="Colaborador não encontrado")
    
    # Delete user account
    await db.users.delete_one({"id": employee["user_id"]})
    
    # Delete employee
    await db.employees.delete_one({"id": employee_id})
    
    # Delete time records
    await db.time_records.delete_many({"employee_id": employee_id})
    
    # Delete leave requests
    await db.leave_requests.delete_many({"employee_id": employee_id})
    
    # Delete folders and documents
    folders = await db.folders.find({"employee_id": employee_id}, {"_id": 0}).to_list(100)
    for folder in folders:
        # Delete files from filesystem
        docs = await db.documents.find({"folder_id": folder["id"]}, {"_id": 0}).to_list(100)
        for doc in docs:
            file_path = Path(doc["file_path"])
            if file_path.exists():
                file_path.unlink()
        await db.documents.delete_many({"folder_id": folder["id"]})
    await db.folders.delete_many({"employee_id": employee_id})
    
    # Delete notifications
    await db.notifications.delete_many({"user_id": employee["user_id"]})
    
    return {"message": "Colaborador eliminado com sucesso"}

# ==================== RESET PASSWORD (Admin function) ====================

class AdminResetPasswordRequest(BaseModel):
    new_password: str

    @field_validator('new_password')
    @classmethod
    def validate_new_password(cls, v):
        is_valid, message = validate_password_strength(v)
        if not is_valid:
            raise ValueError(message)
        return v

@api_router.post("/employees/{employee_id}/reset-password")
async def reset_employee_password(employee_id: str, request: AdminResetPasswordRequest, current_user: dict = Depends(admin_required)):
    """Admin can reset employee password (sets must_change_password = True)"""
    employee = await db.employees.find_one({"id": employee_id}, {"_id": 0})
    if not employee:
        raise HTTPException(status_code=404, detail="Colaborador não encontrado")
    
    # Update password and set must_change_password to True
    new_password_hash = hash_password(request.new_password)
    await db.users.update_one(
        {"id": employee["user_id"]},
        {"$set": {"password": new_password_hash, "must_change_password": True}}
    )
    
    # Create notification
    notification_doc = {
        "id": str(uuid.uuid4()),
        "user_id": employee["user_id"],
        "title": "Palavra-passe Redefinida",
        "message": "A sua palavra-passe foi redefinida pelo administrador. Por favor, altere-a no próximo acesso.",
        "read": False,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.notifications.insert_one(notification_doc)
    
    return {"message": "Palavra-passe redefinida com sucesso. O colaborador deverá alterá-la no próximo acesso."}

# ==================== TIME RECORD ROUTES ====================

def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distância em metros entre dois pontos GPS (fórmula de Haversine)."""
    R = 6371000.0  # raio da Terra em metros
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))

@api_router.post("/time-records", response_model=TimeRecordResponse)
async def create_time_record(record: TimeRecordCreate, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "colaborador":
        raise HTTPException(status_code=403, detail="Apenas colaboradores podem registar ponto")

    employee_id = current_user.get("employee_id")
    if not employee_id:
        raise HTTPException(status_code=400, detail="Utilizador não associado a colaborador")

    # Validate record type
    if record.record_type not in ["entrada", "saida"]:
        raise HTTPException(status_code=400, detail="Tipo de registo inválido. Use 'entrada' ou 'saida'")

    # Cerca geográfica: se o local do colaborador tiver posição e raio definidos,
    # o ponto só é aceite se ele estiver dentro do raio.
    # Colaboradores isentos (ex.: que rodam por várias lojas) não são validados.
    employee = await db.employees.find_one({"id": employee_id}, {"_id": 0})
    if employee and employee.get("location_id") and not employee.get("geofence_exempt"):
        location = await db.locations.find_one({"id": employee["location_id"]}, {"_id": 0})
        if location and location.get("latitude") is not None and location.get("longitude") is not None and location.get("geofence_radius"):
            radius = location["geofence_radius"]
            if record.latitude is None or record.longitude is None:
                raise HTTPException(
                    status_code=400,
                    detail="Ative a localização no telemóvel para poder registar o ponto neste local."
                )
            distance = haversine_meters(record.latitude, record.longitude, location["latitude"], location["longitude"])
            if distance > radius:
                raise HTTPException(
                    status_code=403,
                    detail=f"Está a {int(distance)} m do local de trabalho (limite {radius} m). Aproxime-se para registar o ponto."
                )

    record_id = str(uuid.uuid4())
    record_doc = {
        "id": record_id,
        "employee_id": employee_id,
        "record_type": record.record_type,
        "time": datetime.now(timezone.utc).isoformat(),
        "corrected": False,
        "correction_history": [],
        "latitude": record.latitude,
        "longitude": record.longitude,
        "accuracy": record.accuracy
    }
    await db.time_records.insert_one(record_doc)

    return TimeRecordResponse(**record_doc)

@api_router.get("/time-records", response_model=List[TimeRecordResponse])
async def get_time_records(
    employee_id: Optional[str] = None,
    company_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    query = {}
    
    # Colaboradores can only see their own records
    if current_user.get("role") == "colaborador":
        query["employee_id"] = current_user.get("employee_id")
    elif employee_id:
        query["employee_id"] = employee_id
    
    # Filter by company (admin ou gestor)
    if company_id and current_user.get("role") in MANAGER_ROLES:
        employees = await db.employees.find({"company_id": company_id}, {"_id": 0, "id": 1}).to_list(1000)
        emp_ids = [e["id"] for e in employees]
        query["employee_id"] = {"$in": emp_ids}
    
    # Date filters
    if start_date or end_date:
        query["time"] = {}
        if start_date:
            query["time"]["$gte"] = start_date
        if end_date:
            query["time"]["$lte"] = end_date
    
    records = await db.time_records.find(query, {"_id": 0}).sort("time", -1).to_list(1000)
    
    # Get employee names
    for rec in records:
        employee = await db.employees.find_one({"id": rec["employee_id"]}, {"_id": 0})
        rec["employee_name"] = employee["name"] if employee else None
    
    return [TimeRecordResponse(**r) for r in records]

@api_router.put("/time-records/{record_id}/correct", response_model=TimeRecordResponse)
async def correct_time_record(record_id: str, correction: TimeRecordCorrection, current_user: dict = Depends(admin_required)):
    record = await db.time_records.find_one({"id": record_id}, {"_id": 0})
    if not record:
        raise HTTPException(status_code=404, detail="Registo não encontrado")
    
    # Add to correction history
    correction_entry = {
        "previous_time": record["time"],
        "new_time": correction.time,
        "justification": correction.justification,
        "corrected_by": current_user["user_id"],
        "corrected_at": datetime.now(timezone.utc).isoformat()
    }
    
    await db.time_records.update_one(
        {"id": record_id},
        {
            "$set": {"time": correction.time, "corrected": True},
            "$push": {"correction_history": correction_entry}
        }
    )
    
    # Create notification for employee
    employee = await db.employees.find_one({"id": record["employee_id"]}, {"_id": 0})
    if employee:
        notification_doc = {
            "id": str(uuid.uuid4()),
            "user_id": employee["user_id"],
            "title": "Ponto Corrigido",
            "message": f"O seu registo de ponto foi corrigido. Motivo: {correction.justification}",
            "read": False,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        await db.notifications.insert_one(notification_doc)
    
    updated = await db.time_records.find_one({"id": record_id}, {"_id": 0})
    updated["employee_name"] = employee["name"] if employee else None
    return TimeRecordResponse(**updated)

@api_router.get("/reports/worked-hours")
async def worked_hours_report(
    company_id: Optional[str] = None,
    employee_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    current_user: dict = Depends(admin_manager_required)
):
    """Relatório de horas trabalhadas por colaborador (pares entrada->saída)."""

    def parse_dt(s: str) -> datetime:
        # Aceita tanto '...Z' como '...+00:00'
        return datetime.fromisoformat(s.replace("Z", "+00:00"))

    # Conjunto de colaboradores a considerar
    emp_query = {}
    if company_id:
        emp_query["company_id"] = company_id
    if employee_id:
        emp_query["id"] = employee_id
    employees = await db.employees.find(emp_query, {"_id": 0}).to_list(1000)
    emp_map = {e["id"]: e for e in employees}
    if not emp_map:
        return []

    # Registos de ponto no período
    rec_query = {"employee_id": {"$in": list(emp_map.keys())}}
    if start_date or end_date:
        rec_query["time"] = {}
        if start_date:
            rec_query["time"]["$gte"] = start_date
        if end_date:
            rec_query["time"]["$lte"] = end_date
    records = await db.time_records.find(rec_query, {"_id": 0}).sort("time", 1).to_list(100000)

    by_emp = {}
    for r in records:
        by_emp.setdefault(r["employee_id"], []).append(r)

    results = []
    for emp_id, emp in emp_map.items():
        recs = by_emp.get(emp_id, [])
        total_seconds = 0.0
        days = set()
        pending_in = None
        incomplete = False
        for r in recs:
            t = parse_dt(r["time"])
            days.add(t.date().isoformat())
            if r["record_type"] == "entrada":
                if pending_in is not None:
                    incomplete = True  # duas entradas seguidas sem saída
                pending_in = t
            elif r["record_type"] == "saida":
                if pending_in is not None:
                    delta = (t - pending_in).total_seconds()
                    if delta > 0:
                        total_seconds += delta
                    pending_in = None
                else:
                    incomplete = True  # saída sem entrada
        if pending_in is not None:
            incomplete = True  # entrada sem saída no fim do período

        results.append({
            "employee_id": emp_id,
            "employee_name": emp.get("name"),
            "total_hours": round(total_seconds / 3600, 2),
            "days_worked": len(days),
            "incomplete": incomplete,
        })

    results.sort(key=lambda x: (x["employee_name"] or "").lower())
    return results

# ==================== WORK SCHEDULE ROUTES ====================

@api_router.post("/schedules", response_model=WorkScheduleTemplateResponse)
async def create_schedule_template(template: WorkScheduleTemplateCreate, current_user: dict = Depends(admin_manager_required)):
    template_id = str(uuid.uuid4())
    template_doc = {
        "id": template_id,
        "name": template.name,
        "work_days": template.work_days,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.work_schedule_templates.insert_one(template_doc)
    return WorkScheduleTemplateResponse(**template_doc)

@api_router.get("/schedules", response_model=List[WorkScheduleTemplateResponse])
async def get_schedule_templates(current_user: dict = Depends(admin_manager_required)):
    templates = await db.work_schedule_templates.find({}, {"_id": 0}).sort("created_at", -1).to_list(200)
    return [WorkScheduleTemplateResponse(**t) for t in templates]

@api_router.post("/schedules/assign", response_model=WorkScheduleAssignmentResponse)
async def assign_schedule(assignment: WorkScheduleAssignmentCreate, current_user: dict = Depends(admin_manager_required)):
    employee = await db.employees.find_one({"id": assignment.employee_id}, {"_id": 0})
    if not employee:
        raise HTTPException(status_code=404, detail="Colaborador não encontrado")

    template = await db.work_schedule_templates.find_one({"id": assignment.template_id}, {"_id": 0})
    if not template:
        raise HTTPException(status_code=404, detail="Escala não encontrada")

    try:
        start_dt = datetime.fromisoformat(assignment.start_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Data de início inválida")

    end_dt = None
    if assignment.end_date:
        try:
            end_dt = datetime.fromisoformat(assignment.end_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Data de fim inválida")

    if end_dt and start_dt > end_dt:
        raise HTTPException(status_code=400, detail="Data de início não pode ser posterior à data de fim")

    existing_assignments = await db.work_schedule_assignments.find(
        {"employee_id": employee["id"]},
        {"_id": 0}
    ).to_list(200)

    new_start = start_dt.date()
    new_end = end_dt.date() if end_dt else None

    for existing in existing_assignments:
        existing_start = datetime.fromisoformat(existing["start_date"]).date()
        existing_end_raw = existing.get("end_date")
        existing_end = datetime.fromisoformat(existing_end_raw).date() if existing_end_raw else None
        existing_end_cmp = existing_end or date.max
        new_end_cmp = new_end or date.max

        if new_start <= existing_end_cmp and new_end_cmp >= existing_start:
            raise HTTPException(status_code=400, detail="Já existe uma escala ativa nesse período")

    assignment_id = str(uuid.uuid4())
    assignment_doc = {
        "id": assignment_id,
        "employee_id": employee["id"],
        "template_id": template["id"],
        "work_days": template.get("work_days", []),
        "start_date": assignment.start_date,
        "end_date": assignment.end_date,
        "created_at": datetime.now(timezone.utc).isoformat()
    }

    await db.work_schedule_assignments.insert_one(assignment_doc)

    return WorkScheduleAssignmentResponse(
        **assignment_doc,
        employee_name=employee["name"],
        template_name=template["name"]
    )

@api_router.get("/schedules/assignments", response_model=List[WorkScheduleAssignmentResponse])
async def get_schedule_assignments(employee_id: Optional[str] = None, current_user: dict = Depends(admin_manager_required)):
    query = {}
    if employee_id:
        query["employee_id"] = employee_id

    assignments = await db.work_schedule_assignments.find(query, {"_id": 0}).sort("start_date", -1).to_list(200)

    for assignment in assignments:
        employee = await db.employees.find_one({"id": assignment["employee_id"]}, {"_id": 0})
        template = await db.work_schedule_templates.find_one({"id": assignment["template_id"]}, {"_id": 0})
        assignment["employee_name"] = employee["name"] if employee else None
        assignment["template_name"] = template["name"] if template else None
        if not assignment.get("work_days") and template:
            assignment["work_days"] = template.get("work_days", [])

    return [WorkScheduleAssignmentResponse(**a) for a in assignments]

@api_router.put("/schedules/{template_id}", response_model=WorkScheduleTemplateResponse)
async def update_schedule_template(template_id: str, template: WorkScheduleTemplateCreate, current_user: dict = Depends(admin_manager_required)):
    result = await db.work_schedule_templates.update_one(
        {"id": template_id},
        {"$set": {"name": template.name, "work_days": template.work_days}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Escala não encontrada")
    # Manter os dias coerentes nas atribuições que usam esta escala
    await db.work_schedule_assignments.update_many(
        {"template_id": template_id},
        {"$set": {"work_days": template.work_days}}
    )
    updated = await db.work_schedule_templates.find_one({"id": template_id}, {"_id": 0})
    return WorkScheduleTemplateResponse(**updated)

@api_router.delete("/schedules/assignments/{assignment_id}")
async def delete_schedule_assignment(assignment_id: str, current_user: dict = Depends(admin_manager_required)):
    result = await db.work_schedule_assignments.delete_one({"id": assignment_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Atribuição não encontrada")
    return {"message": "Atribuição removida com sucesso"}

@api_router.delete("/schedules/{template_id}")
async def delete_schedule_template(template_id: str, current_user: dict = Depends(admin_manager_required)):
    result = await db.work_schedule_templates.delete_one({"id": template_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Escala não encontrada")
    # Remove também as atribuições desta escala
    await db.work_schedule_assignments.delete_many({"template_id": template_id})
    return {"message": "Escala eliminada com sucesso"}

# ==================== LEAVE REQUEST ROUTES ====================

@api_router.post("/admin/leave", response_model=LeaveRequestResponse)
async def create_admin_leave(request: AdminLeaveCreate, current_user: dict = Depends(admin_manager_required)):
    """
    Create leave directly by admin/manager without approval flow.
    """
    employee = await db.employees.find_one({"id": request.user_id}, {"_id": 0})
    if not employee:
        employee = await db.employees.find_one({"user_id": request.user_id}, {"_id": 0})

    if not employee:
        raise HTTPException(status_code=404, detail="Colaborador não encontrado")

    try:
        start_dt = datetime.fromisoformat(request.start_date)
        end_dt = datetime.fromisoformat(request.end_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Datas inválidas. Use o formato AAAA-MM-DD")

    if start_dt > end_dt:
        raise HTTPException(status_code=400, detail="Data de início não pode ser posterior à data de fim")

    overlapping = await db.leave_requests.find_one(
        {
            "employee_id": employee["id"],
            "status": {"$ne": "recusado"},
            "start_date": {"$lte": request.end_date},
            "end_date": {"$gte": request.start_date}
        },
        {"_id": 0}
    )

    if overlapping:
        raise HTTPException(status_code=400, detail="Já existe um registo de férias/ausência nesse período")

    created_by_role = "gestor" if current_user.get("role") == "gerente" else "admin"

    request_id = str(uuid.uuid4())
    counted_days = await calculate_leave_counted_days(employee["id"], request.start_date, request.end_date)
    audit_log = [build_audit_entry("criado_manual", current_user)]
    request_doc = {
        "id": request_id,
        "employee_id": employee["id"],
        "leave_type": request.leave_type,
        "start_date": request.start_date,
        "end_date": request.end_date,
        "status": "aprovado",
        "observation": request.reason,
        "document_id": None,
        "admin_response": None,
        "created_by": created_by_role,
        "is_paid": request.is_paid,
        "counted_days": counted_days,
        "audit_log": audit_log,
        "created_at": datetime.now(timezone.utc).isoformat()
    }

    await db.leave_requests.insert_one(request_doc)

    return LeaveRequestResponse(**request_doc, employee_name=employee["name"])

@api_router.post("/leave-requests", response_model=LeaveRequestResponse)
async def create_leave_request(request: LeaveRequestCreate, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ["colaborador", "gerente"]:
        raise HTTPException(status_code=403, detail="Apenas colaboradores ou gestores podem criar pedidos")

    employee_id = current_user.get("employee_id")
    if not employee_id:
        raise HTTPException(status_code=400, detail="Utilizador não associado a colaborador")

    if not current_user.get("name"):
        user_doc = await db.users.find_one({"id": current_user.get("user_id")}, {"_id": 0, "name": 1, "role": 1})
        if user_doc:
            current_user["name"] = user_doc.get("name")
            current_user["role"] = user_doc.get("role", current_user.get("role"))
    valid_types = ["ferias", "falta", "doenca", "folga"]
    if request.leave_type not in valid_types:
        raise HTTPException(status_code=400, detail=f"Tipo inválido. Use: {', '.join(valid_types)}")

    request_id = str(uuid.uuid4())
    counted_days = await calculate_leave_counted_days(employee_id, request.start_date, request.end_date)
    audit_log = [build_audit_entry("criado", current_user)]
    request_doc = {
        "id": request_id,
        "employee_id": employee_id,
        "leave_type": request.leave_type,
        "start_date": request.start_date,
        "end_date": request.end_date,
        "status": "pendente",
        "observation": request.observation,
        "document_id": None,
        "admin_response": None,
        "created_by": "gestor" if current_user.get("role") == "gerente" else "colaborador",
        "is_paid": None,
        "counted_days": counted_days,
        "audit_log": audit_log,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.leave_requests.insert_one(request_doc)

    # Notify admins
    employee = await db.employees.find_one({"id": employee_id}, {"_id": 0})
    admins = await db.users.find({"role": "admin"}, {"_id": 0}).to_list(100)

    leave_type_labels = {"ferias": "Férias", "falta": "Falta", "doenca": "Doença", "folga": "Folga"}

    for admin in admins:
        notification_doc = {
            "id": str(uuid.uuid4()),
            "user_id": admin["id"],
            "title": "Novo Pedido de Ausência",
            "message": f"{employee['name'] if employee else 'Colaborador'} solicitou {leave_type_labels.get(request.leave_type, request.leave_type)}",
            "read": False,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        await db.notifications.insert_one(notification_doc)

    # Aviso por email aos admins/gestores (não bloqueia se o email falhar)
    await notify_managers_of_leave_request(
        employee["name"] if employee else "Colaborador",
        request.leave_type,
        request.start_date,
        request.end_date,
        request.observation
    )

    return LeaveRequestResponse(**request_doc, employee_name=employee["name"] if employee else None)

@api_router.get("/leave-requests", response_model=List[LeaveRequestResponse])
async def get_leave_requests(
    employee_id: Optional[str] = None,
    company_id: Optional[str] = None,
    status: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    query = {}
    
    # Colaboradores can only see their own requests
    if current_user.get("role") == "colaborador":
        query["employee_id"] = current_user.get("employee_id")
    elif employee_id:
        query["employee_id"] = employee_id
    
    # Filter by company (admin ou gestor)
    if company_id and current_user.get("role") in MANAGER_ROLES:
        employees = await db.employees.find({"company_id": company_id}, {"_id": 0, "id": 1}).to_list(1000)
        emp_ids = [e["id"] for e in employees]
        query["employee_id"] = {"$in": emp_ids}
    
    if status:
        query["status"] = status
    
    requests = await db.leave_requests.find(query, {"_id": 0}).sort("created_at", -1).to_list(1000)

    # Get employee names
    for req in requests:
        employee = await db.employees.find_one({"id": req["employee_id"]}, {"_id": 0})
        req["employee_name"] = employee["name"] if employee else None
        req["counted_days"] = await calculate_leave_counted_days(
            req["employee_id"],
            req["start_date"],
            req["end_date"]
        )

    return [LeaveRequestResponse(**r) for r in requests]

class LeaveRequestResponseModel(BaseModel):
    status: str
    response: Optional[str] = None

class LeaveRequestUpdate(BaseModel):
    start_date: str = Field(alias="startDate")
    end_date: str = Field(alias="endDate")
    observation: Optional[str] = None

    model_config = {"populate_by_name": True}

@api_router.put("/leave-requests/{request_id}", response_model=LeaveRequestResponse)
async def update_leave_request(
    request_id: str,
    data: LeaveRequestUpdate,
    current_user: dict = Depends(admin_manager_required)
):
    leave_request = await db.leave_requests.find_one({"id": request_id}, {"_id": 0})
    if not leave_request:
        raise HTTPException(status_code=404, detail="Pedido não encontrado")

    try:
        start_dt = datetime.fromisoformat(data.start_date)
        end_dt = datetime.fromisoformat(data.end_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Datas inválidas. Use o formato AAAA-MM-DD")

    if start_dt > end_dt:
        raise HTTPException(status_code=400, detail="Data de início não pode ser posterior à data de fim")

    overlapping = await db.leave_requests.find_one(
        {
            "employee_id": leave_request["employee_id"],
            "id": {"$ne": request_id},
            "status": {"$ne": "recusado"},
            "start_date": {"$lte": data.end_date},
            "end_date": {"$gte": data.start_date}
        },
        {"_id": 0}
    )

    if overlapping:
        raise HTTPException(status_code=400, detail="Já existe um registo de férias/ausência nesse período")

    counted_days = await calculate_leave_counted_days(
        leave_request["employee_id"],
        data.start_date,
        data.end_date
    )

    audit_entry = build_audit_entry("editado", current_user)

    await db.leave_requests.update_one(
        {"id": request_id},
        {
            "$set": {
                "start_date": data.start_date,
                "end_date": data.end_date,
                "observation": data.observation,
                "counted_days": counted_days
            },
            "$push": {"audit_log": audit_entry}
        }
    )

    updated = await db.leave_requests.find_one({"id": request_id}, {"_id": 0})
    employee = await db.employees.find_one({"id": updated["employee_id"]}, {"_id": 0})
    updated["employee_name"] = employee["name"] if employee else None
    updated["counted_days"] = await calculate_leave_counted_days(
        updated["employee_id"],
        updated["start_date"],
        updated["end_date"]
    )

    return LeaveRequestResponse(**updated)

@api_router.put("/leave-requests/{request_id}/respond")
async def respond_leave_request(
    request_id: str,
    data: LeaveRequestResponseModel,
    current_user: dict = Depends(admin_manager_required)
):
    if data.status not in ["aprovado", "recusado"]:
        raise HTTPException(status_code=400, detail="Status inválido. Use 'aprovado' ou 'recusado'")
    
    leave_request = await db.leave_requests.find_one({"id": request_id}, {"_id": 0})
    if not leave_request:
        raise HTTPException(status_code=404, detail="Pedido não encontrado")

    audit_entry = build_audit_entry(
        "aprovado" if data.status == "aprovado" else "recusado",
        current_user
    )

    await db.leave_requests.update_one(
        {"id": request_id},
        {
            "$set": {"status": data.status, "admin_response": data.response},
            "$push": {"audit_log": audit_entry}
        }
    )
    
    # Notify employee
    employee = await db.employees.find_one({"id": leave_request["employee_id"]}, {"_id": 0})
    if employee:
        status_label = "aprovado" if data.status == "aprovado" else "recusado"
        notification_doc = {
            "id": str(uuid.uuid4()),
            "user_id": employee["user_id"],
            "title": f"Pedido {status_label.capitalize()}",
            "message": f"O seu pedido de ausência foi {status_label}." + (f" Resposta: {data.response}" if data.response else ""),
            "read": False,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        await db.notifications.insert_one(notification_doc)

        # Email ao colaborador com a decisão (não bloqueia se o email falhar)
        type_label = "férias" if leave_request.get("leave_type") == "ferias" else "ausência"
        await notify_employee_of_leave_decision(
            employee.get("email"),
            employee.get("name"),
            status_label,
            type_label,
            leave_request.get("start_date"),
            leave_request.get("end_date"),
            data.response,
        )

    updated = await db.leave_requests.find_one({"id": request_id}, {"_id": 0})
    updated["employee_name"] = employee["name"] if employee else None
    updated["counted_days"] = await calculate_leave_counted_days(
        updated["employee_id"],
        updated["start_date"],
        updated["end_date"]
    )

    return LeaveRequestResponse(**updated)

@api_router.delete("/leave-requests/{request_id}")
async def delete_leave_request(request_id: str, current_user: dict = Depends(admin_manager_required)):
    """Eliminar um pedido de férias/ausência (ex.: limpar os recusados).

    Os dias de férias usados são recalculados automaticamente a partir dos
    pedidos aprovados, por isso não é preciso ajustar nada manualmente.
    """
    leave_request = await db.leave_requests.find_one({"id": request_id}, {"_id": 0})
    if not leave_request:
        raise HTTPException(status_code=404, detail="Pedido não encontrado")
    await db.leave_requests.delete_one({"id": request_id})
    return {"message": "Pedido eliminado com sucesso"}

# ==================== FOLDER ROUTES ====================

@api_router.post("/folders", response_model=FolderResponse)
async def create_folder(folder: FolderCreate, current_user: dict = Depends(admin_required)):
    # Verify employee exists
    employee = await db.employees.find_one({"id": folder.employee_id}, {"_id": 0})
    if not employee:
        raise HTTPException(status_code=404, detail="Colaborador não encontrado")
    
    folder_id = str(uuid.uuid4())
    folder_doc = {
        "id": folder_id,
        "name": folder.name,
        "employee_id": folder.employee_id,
        "allow_employee_upload": folder.allow_employee_upload,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.folders.insert_one(folder_doc)
    return FolderResponse(**folder_doc)

@api_router.get("/folders", response_model=List[FolderResponse])
async def get_folders(employee_id: str, current_user: dict = Depends(get_current_user)):
    # Colaboradores can only see their own folders
    if current_user.get("role") == "colaborador" and current_user.get("employee_id") != employee_id:
        raise HTTPException(status_code=403, detail="Acesso negado")
    
    folders = await db.folders.find({"employee_id": employee_id}, {"_id": 0}).to_list(100)
    return [FolderResponse(**f) for f in folders]

@api_router.put("/folders/{folder_id}", response_model=FolderResponse)
async def update_folder(folder_id: str, folder: FolderCreate, current_user: dict = Depends(admin_required)):
    result = await db.folders.update_one(
        {"id": folder_id},
        {"$set": {"name": folder.name, "allow_employee_upload": folder.allow_employee_upload}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Pasta não encontrada")
    
    updated = await db.folders.find_one({"id": folder_id}, {"_id": 0})
    return FolderResponse(**updated)

@api_router.delete("/folders/{folder_id}")
async def delete_folder(folder_id: str, current_user: dict = Depends(admin_required)):
    folder = await db.folders.find_one({"id": folder_id}, {"_id": 0})
    if not folder:
        raise HTTPException(status_code=404, detail="Pasta não encontrada")
    
    # Delete documents in folder
    docs = await db.documents.find({"folder_id": folder_id}, {"_id": 0}).to_list(100)
    for doc in docs:
        file_path = Path(doc["file_path"])
        if file_path.exists():
            file_path.unlink()
    await db.documents.delete_many({"folder_id": folder_id})
    
    await db.folders.delete_one({"id": folder_id})
    return {"message": "Pasta eliminada com sucesso"}

# ==================== DOCUMENT ROUTES ====================

@api_router.post("/documents", response_model=DocumentResponse)
async def upload_document(
    folder_id: str = Form(...),
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user)
):
    folder = await db.folders.find_one({"id": folder_id}, {"_id": 0})
    if not folder:
        raise HTTPException(status_code=404, detail="Pasta não encontrada")
    
    # Check permissions
    if current_user.get("role") == "colaborador":
        if current_user.get("employee_id") != folder["employee_id"]:
            raise HTTPException(status_code=403, detail="Acesso negado")
        if not folder["allow_employee_upload"]:
            raise HTTPException(status_code=403, detail="Não tem permissão para enviar documentos para esta pasta")
    
    # Save file
    file_id = str(uuid.uuid4())
    file_extension = Path(file.filename).suffix
    file_name = f"{file_id}{file_extension}"
    file_path = UPLOAD_DIR / file_name
    
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    # Get uploader info
    user = await db.users.find_one({"id": current_user["user_id"]}, {"_id": 0})
    
    doc_id = str(uuid.uuid4())
    doc_record = {
        "id": doc_id,
        "name": file.filename,
        "folder_id": folder_id,
        "employee_id": folder["employee_id"],
        "uploaded_by": current_user["user_id"],
        "uploaded_by_name": user["name"] if user else None,
        "file_path": str(file_path),
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.documents.insert_one(doc_record)
    
    # Notify if a manager uploaded for the employee
    if current_user.get("role") in MANAGER_ROLES:
        employee = await db.employees.find_one({"id": folder["employee_id"]}, {"_id": 0})
        if employee:
            notification_doc = {
                "id": str(uuid.uuid4()),
                "user_id": employee["user_id"],
                "title": "Novo Documento",
                "message": f"Foi adicionado um novo documento na pasta '{folder['name']}'",
                "read": False,
                "created_at": datetime.now(timezone.utc).isoformat()
            }
            await db.notifications.insert_one(notification_doc)
    
    return DocumentResponse(**doc_record, folder_name=folder["name"])

@api_router.get("/documents", response_model=List[DocumentResponse])
async def get_documents(
    folder_id: Optional[str] = None,
    employee_id: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    query = {}
    
    if folder_id:
        folder = await db.folders.find_one({"id": folder_id}, {"_id": 0})
        if not folder:
            raise HTTPException(status_code=404, detail="Pasta não encontrada")
        
        # Check permissions
        if current_user.get("role") == "colaborador" and current_user.get("employee_id") != folder["employee_id"]:
            raise HTTPException(status_code=403, detail="Acesso negado")
        
        query["folder_id"] = folder_id
    elif employee_id:
        # Check permissions
        if current_user.get("role") == "colaborador" and current_user.get("employee_id") != employee_id:
            raise HTTPException(status_code=403, detail="Acesso negado")
        query["employee_id"] = employee_id
    elif current_user.get("role") == "colaborador":
        query["employee_id"] = current_user.get("employee_id")
    
    documents = await db.documents.find(query, {"_id": 0}).sort("created_at", -1).to_list(1000)
    
    # Get folder names
    for doc in documents:
        folder = await db.folders.find_one({"id": doc["folder_id"]}, {"_id": 0})
        doc["folder_name"] = folder["name"] if folder else None
    
    return [DocumentResponse(**d) for d in documents]

@api_router.get("/documents/{document_id}/download")
async def download_document(document_id: str, current_user: dict = Depends(get_current_user)):
    doc = await db.documents.find_one({"id": document_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Documento não encontrado")
    
    # Check permissions
    if current_user.get("role") == "colaborador" and current_user.get("employee_id") != doc["employee_id"]:
        raise HTTPException(status_code=403, detail="Acesso negado")
    
    file_path = Path(doc["file_path"])
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Ficheiro não encontrado")
    
    return FileResponse(file_path, filename=doc["name"])

@api_router.delete("/documents/{document_id}")
async def delete_document(document_id: str, current_user: dict = Depends(admin_required)):
    doc = await db.documents.find_one({"id": document_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Documento não encontrado")
    
    # Delete file
    file_path = Path(doc["file_path"])
    if file_path.exists():
        file_path.unlink()
    
    await db.documents.delete_one({"id": document_id})
    return {"message": "Documento eliminado com sucesso"}

# ==================== NOTIFICATION ROUTES ====================

@api_router.get("/notifications", response_model=List[NotificationResponse])
async def get_notifications(current_user: dict = Depends(get_current_user)):
    notifications = await db.notifications.find(
        {"user_id": current_user["user_id"]},
        {"_id": 0}
    ).sort("created_at", -1).to_list(100)
    return [NotificationResponse(**n) for n in notifications]

@api_router.put("/notifications/{notification_id}/read")
async def mark_notification_read(notification_id: str, current_user: dict = Depends(get_current_user)):
    result = await db.notifications.update_one(
        {"id": notification_id, "user_id": current_user["user_id"]},
        {"$set": {"read": True}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Notificação não encontrada")
    return {"message": "Notificação marcada como lida"}

@api_router.put("/notifications/read-all")
async def mark_all_notifications_read(current_user: dict = Depends(get_current_user)):
    await db.notifications.update_many(
        {"user_id": current_user["user_id"]},
        {"$set": {"read": True}}
    )
    return {"message": "Todas as notificações marcadas como lidas"}

# ==================== DASHBOARD ROUTES ====================

@api_router.get("/dashboard/admin")
async def get_admin_dashboard(company_id: Optional[str] = None, current_user: dict = Depends(admin_manager_required)):
    query = {}
    if company_id:
        query["company_id"] = company_id
    
    # Total employees
    total_employees = await db.employees.count_documents(query)
    
    # Total companies
    total_companies = await db.companies.count_documents({})
    
    # Pending requests
    pending_query = {"status": "pendente"}
    if company_id:
        employees = await db.employees.find({"company_id": company_id}, {"_id": 0, "id": 1}).to_list(1000)
        emp_ids = [e["id"] for e in employees]
        pending_query["employee_id"] = {"$in": emp_ids}
    pending_requests = await db.leave_requests.count_documents(pending_query)
    
    # Today's records
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    today_query = {"time": {"$gte": today}}
    if company_id:
        today_query["employee_id"] = {"$in": emp_ids}
    today_records = await db.time_records.count_documents(today_query)
    
    # Employees by company
    companies = await db.companies.find({}, {"_id": 0}).to_list(100)
    employees_by_company = []
    for company in companies:
        count = await db.employees.count_documents({"company_id": company["id"]})
        employees_by_company.append({"company": company["name"], "count": count})
    
    # Recent requests
    recent_query = {}
    if company_id:
        recent_query["employee_id"] = {"$in": emp_ids}
    recent_requests = await db.leave_requests.find(recent_query, {"_id": 0}).sort("created_at", -1).to_list(5)
    for req in recent_requests:
        employee = await db.employees.find_one({"id": req["employee_id"]}, {"_id": 0})
        req["employee_name"] = employee["name"] if employee else None
    
    # ===== Enriquecimento: quem está hoje + aniversários =====
    emp_filter = {"company_id": company_id} if company_id else {}
    all_emps = await db.employees.find(
        emp_filter,
        {"_id": 0, "id": 1, "name": 1, "photo": 1, "birth_date": 1,
         "position": 1, "location_id": 1, "company_id": 1},
    ).to_list(2000)
    emp_id_set = {e["id"] for e in all_emps}
    emp_by_id = {e["id"]: e for e in all_emps}

    # Mapas de apoio para enriquecer os cartões (poucos queries, sem loops)
    locations_all = await db.locations.find({}, {"_id": 0, "id": 1, "name": 1}).to_list(500)
    location_name_by_id = {loc["id"]: loc.get("name") for loc in locations_all}
    companies_all = await db.companies.find({}, {"_id": 0, "id": 1, "name": 1}).to_list(200)
    company_name_by_id = {c["id"]: c.get("name") for c in companies_all}

    today_date = datetime.now(timezone.utc).date()
    today_str = today_date.isoformat()

    # De férias/ausência hoje (aprovado e cobre hoje)
    on_leave_ids = set()
    leave_type_by_emp = {}
    leave_end_by_emp = {}
    leaves_today = await db.leave_requests.find(
        {"status": "aprovado", "start_date": {"$lte": today_str}, "end_date": {"$gte": today_str}},
        {"_id": 0, "employee_id": 1, "leave_type": 1, "end_date": 1}
    ).to_list(2000)
    for lv in leaves_today:
        if lv["employee_id"] in emp_id_set:
            on_leave_ids.add(lv["employee_id"])
            # férias > folga > ausência (prioridade se houver mais do que um)
            existing = leave_type_by_emp.get(lv["employee_id"])
            if existing != "ferias":
                leave_type_by_emp[lv["employee_id"]] = lv.get("leave_type")
                leave_end_by_emp[lv["employee_id"]] = lv.get("end_date")

    # A trabalhar agora (último registo de hoje = entrada)
    rec_q = {"time": {"$gte": today_str}}
    if company_id:
        rec_q["employee_id"] = {"$in": list(emp_id_set)}
    records_today = await db.time_records.find(
        rec_q, {"_id": 0, "employee_id": 1, "record_type": 1, "time": 1}
    ).sort("time", 1).to_list(5000)
    last_type = {}
    first_entry_by_emp = {}  # hora "HH:MM" da PRIMEIRA entrada de hoje
    for r in records_today:
        eid = r["employee_id"]
        last_type[eid] = r["record_type"]
        if r["record_type"] == "entrada" and eid not in first_entry_by_emp:
            t = r.get("time")
            if t:
                try:
                    first_entry_by_emp[eid] = datetime.fromisoformat(t).strftime("%H:%M")
                except (ValueError, TypeError):
                    first_entry_by_emp[eid] = None
    working_ids = [eid for eid, t in last_type.items() if t == "entrada" and eid not in on_leave_ids and eid in emp_id_set]

    # Atribuições de escala por colaborador (pré-carregadas, sem query por pessoa)
    assignments_all = await db.work_schedule_assignments.find(
        {"employee_id": {"$in": list(emp_id_set)}}, {"_id": 0}
    ).to_list(5000)
    # Agrupar atribuições por colaborador (dict simples, sem defaultdict)
    assignments_by_emp = {}
    for a in assignments_all:
        assignments_by_emp.setdefault(a["employee_id"], []).append(a)

    # Mapa de templates (work_days + nome), para resolver a escala ativa hoje
    template_ids = {a.get("template_id") for a in assignments_all if a.get("template_id")}
    templates_by_id = {}
    if template_ids:
        templates = await db.work_schedule_templates.find(
            {"id": {"$in": list(template_ids)}}, {"_id": 0, "id": 1, "name": 1, "work_days": 1}
        ).to_list(500)
        templates_by_id = {t["id"]: t for t in templates}

    def _schedule_today(eid):
        """Escala ativa hoje. Devolve (work_days, name) com a atribuição ativa,
        ou (None, None) se não houver atribuição a cobrir hoje. work_days pode ser
        lista vazia se a atribuição não definir dias."""
        assignment = find_schedule_assignment(assignments_by_emp.get(eid, []), today_date)
        if not assignment:
            return None, None
        tpl = templates_by_id.get(assignment.get("template_id"), {})
        work_days = assignment.get("work_days") or tpl.get("work_days") or []
        return list(work_days), tpl.get("name")

    def _mini(eid):
        e = emp_by_id.get(eid, {})
        sched_days, sched_name = _schedule_today(eid)
        item = {
            "id": eid,
            "name": e.get("name"),
            "photo": e.get("photo"),
            "position": e.get("position"),
            "location_name": location_name_by_id.get(e.get("location_id")),
            "company_name": company_name_by_id.get(e.get("company_id")),
            # Para o frontend: só consideramos "tem escala" se houver dias definidos
            "schedule_days": sched_days if sched_days else None,
            "schedule_name": sched_name if sched_days else None,
        }
        if eid in working_ids:
            item["since"] = first_entry_by_emp.get(eid)
        if eid in on_leave_ids:
            item["until"] = leave_end_by_emp.get(eid)
        return item

    vacation_ids = [eid for eid in on_leave_ids if leave_type_by_emp.get(eid) == "ferias"]
    dayoff_ids = [eid for eid in on_leave_ids if leave_type_by_emp.get(eid) == "folga"]
    absent_ids = [eid for eid in on_leave_ids if leave_type_by_emp.get(eid) not in ("ferias", "folga")]

    # Folga pela escala: tem escala ativa hoje mas hoje não é dia de trabalho
    today_weekday = today_date.weekday()  # 0=Seg ... 5=Sáb, 6=Dom
    schedule_dayoff_ids = []
    for eid in emp_id_set:
        # Ausência aprovada e "a trabalhar" têm prioridade
        if eid in on_leave_ids or eid in working_ids:
            continue
        sched_days, _ = _schedule_today(eid)
        if sched_days is None:
            continue
        if today_weekday not in sched_days:
            schedule_dayoff_ids.append(eid)

    # Juntar folga por pedido + folga por escala, sem duplicar
    dayoff_all = list(dayoff_ids)
    for eid in schedule_dayoff_ids:
        if eid not in dayoff_all:
            dayoff_all.append(eid)

    whos_in = {
        "working": [_mini(eid) for eid in working_ids[:18]],
        "vacation": [_mini(eid) for eid in vacation_ids[:18]],
        "dayoff": [_mini(eid) for eid in dayoff_all[:18]],
        "absent": [_mini(eid) for eid in absent_ids[:18]],
        "on_leave": [_mini(eid) for eid in list(on_leave_ids)[:18]],
    }

    # Aniversários nos próximos 30 dias
    birthdays = []
    for e in all_emps:
        bd = e.get("birth_date")
        if not bd:
            continue
        try:
            d = datetime.fromisoformat(bd).date()
            try:
                nb = d.replace(year=today_date.year)
            except ValueError:
                nb = d.replace(year=today_date.year, day=28)  # 29 fev
            if nb < today_date:
                try:
                    nb = d.replace(year=today_date.year + 1)
                except ValueError:
                    nb = d.replace(year=today_date.year + 1, day=28)
            days = (nb - today_date).days
            if days <= 30:
                birthdays.append({
                    "name": e.get("name"),
                    "photo": e.get("photo"),
                    "position": e.get("position"),
                    "company_name": company_name_by_id.get(e.get("company_id")),
                    "location_name": location_name_by_id.get(e.get("location_id")),
                    "date": nb.isoformat(),
                    "days_until": days,
                })
        except ValueError:
            continue
    birthdays.sort(key=lambda x: x["days_until"])
    birthdays = birthdays[:6]

    # Próximas férias: pedidos aprovados que começam depois de hoje
    upcoming_leaves = []
    q = {"status": "aprovado", "leave_type": "ferias", "start_date": {"$gt": today_str}}
    if company_id:
        q["employee_id"] = {"$in": list(emp_id_set)}
    rows = await db.leave_requests.find(q, {"_id": 0}).sort("start_date", 1).to_list(30)
    for lv in rows:
        emp = emp_by_id.get(lv["employee_id"])
        if not emp:  # fora do scope da empresa
            continue
        start = datetime.fromisoformat(lv["start_date"]).date()
        days_until = (start - today_date).days
        upcoming_leaves.append({
            "employee_name": emp.get("name"),
            "photo": emp.get("photo"),
            "position": emp.get("position"),
            "company_name": company_name_by_id.get(emp.get("company_id")),
            "location_name": location_name_by_id.get(emp.get("location_id")),
            "leave_type": lv.get("leave_type"),
            "start_date": lv["start_date"],
            "end_date": lv["end_date"],
            "days_until": days_until,
        })
    upcoming_leaves = upcoming_leaves[:6]

    return {
        "total_employees": total_employees,
        "total_companies": total_companies,
        "pending_requests": pending_requests,
        "today_records": today_records,
        "on_leave_today": len(on_leave_ids),
        "working_now": len(working_ids),
        "employees_by_company": employees_by_company,
        "recent_requests": recent_requests,
        "whos_in": whos_in,
        "upcoming_birthdays": birthdays,
        "upcoming_leaves": upcoming_leaves,
    }

@api_router.get("/dashboard/employee")
async def get_employee_dashboard(current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "colaborador":
        raise HTTPException(status_code=403, detail="Apenas para colaboradores")
    
    employee_id = current_user.get("employee_id")
    
    # Get employee info
    employee = await db.employees.find_one({"id": employee_id}, {"_id": 0})
    
    # Calculate vacation days used and available
    if employee:
        vacation_used = await calculate_vacation_days_used(employee_id)
        employee["vacation_days_used"] = vacation_used
        employee["vacation_days_available"] = employee["vacation_days"] - vacation_used
    
    # Upcoming leave
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    upcoming_leave = await db.leave_requests.find(
        {"employee_id": employee_id, "status": "aprovado", "start_date": {"$gte": today}},
        {"_id": 0}
    ).sort("start_date", 1).to_list(5)
    
    # Recent time records
    recent_records = await db.time_records.find(
        {"employee_id": employee_id},
        {"_id": 0}
    ).sort("time", -1).to_list(10)
    
    # Pending requests
    pending_requests = await db.leave_requests.find(
        {"employee_id": employee_id, "status": "pendente"},
        {"_id": 0}
    ).to_list(10)

    for request in pending_requests:
        request["counted_days"] = await calculate_leave_counted_days(
            employee_id,
            request["start_date"],
            request["end_date"]
        )
    
    # Unread notifications count
    unread_count = await db.notifications.count_documents(
        {"user_id": current_user["user_id"], "read": False}
    )
    
    return {
        "employee": employee,
        "upcoming_leave": upcoming_leave,
        "recent_records": recent_records,
        "pending_requests": pending_requests,
        "unread_notifications": unread_count
    }

@api_router.get("/calendar/leaves")
async def get_calendar_leaves(
    company_id: Optional[str] = None,
    month: Optional[int] = None,
    year: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    query = {"status": "aprovado"}
    
    # Filter by company for managers
    if company_id and current_user.get("role") in MANAGER_ROLES:
        employees = await db.employees.find({"company_id": company_id}, {"_id": 0, "id": 1}).to_list(1000)
        emp_ids = [e["id"] for e in employees]
        query["employee_id"] = {"$in": emp_ids}
    elif current_user.get("role") == "colaborador":
        query["employee_id"] = current_user.get("employee_id")
    
    # Date filtering
    if month and year:
        start = f"{year}-{month:02d}-01"
        if month == 12:
            end = f"{year + 1}-01-01"
        else:
            end = f"{year}-{month + 1:02d}-01"
        query["$or"] = [
            {"start_date": {"$gte": start, "$lt": end}},
            {"end_date": {"$gte": start, "$lt": end}},
            {"$and": [{"start_date": {"$lt": start}}, {"end_date": {"$gte": end}}]}
        ]
    
    leaves = await db.leave_requests.find(query, {"_id": 0}).to_list(1000)

    # Get employee names
    for leave in leaves:
        employee = await db.employees.find_one({"id": leave["employee_id"]}, {"_id": 0})
        leave["employee_name"] = employee["name"] if employee else None
        leave["counted_days"] = await calculate_leave_counted_days(
            leave["employee_id"],
            leave["start_date"],
            leave["end_date"]
        )

    return leaves

# ==================== MARKETING — CAMPANHAS ====================

class CampaignCreate(BaseModel):
    name: str
    type: str = "campanha"          # campanha | promocao | evento | cupao
    company_id: Optional[str] = None  # None = todo o grupo
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    status: str = "planeada"        # planeada | ativa | terminada
    channel: Optional[str] = None   # ex.: Instagram, Facebook, Loja...
    budget: Optional[float] = None
    description: Optional[str] = None
    result: Optional[str] = None

class CampaignResponse(BaseModel):
    id: str
    name: str
    type: str
    company_id: Optional[str] = None
    company_name: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    status: str
    channel: Optional[str] = None
    budget: Optional[float] = None
    description: Optional[str] = None
    result: Optional[str] = None
    created_at: str

async def _campaign_response(doc: dict) -> CampaignResponse:
    company_name = None
    if doc.get("company_id"):
        company = await db.companies.find_one({"id": doc["company_id"]}, {"_id": 0, "name": 1})
        company_name = company["name"] if company else None
    return CampaignResponse(**doc, company_name=company_name)

@api_router.get("/marketing/campaigns", response_model=List[CampaignResponse])
async def list_campaigns(company_id: Optional[str] = None, status: Optional[str] = None,
                         current_user: dict = Depends(admin_required)):
    query = {}
    if company_id:
        query["company_id"] = company_id
    if status:
        query["status"] = status
    docs = await db.mkt_campaigns.find(query, {"_id": 0}).sort("created_at", -1).to_list(1000)
    return [await _campaign_response(d) for d in docs]

@api_router.post("/marketing/campaigns", response_model=CampaignResponse)
async def create_campaign(campaign: CampaignCreate, current_user: dict = Depends(admin_required)):
    if campaign.company_id:
        company = await db.companies.find_one({"id": campaign.company_id}, {"_id": 0})
        if not company:
            raise HTTPException(status_code=404, detail="Empresa não encontrada")
    doc = {
        "id": str(uuid.uuid4()),
        **campaign.model_dump(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": current_user.get("user_id"),
    }
    await db.mkt_campaigns.insert_one(doc)
    return await _campaign_response(doc)

@api_router.put("/marketing/campaigns/{campaign_id}", response_model=CampaignResponse)
async def update_campaign(campaign_id: str, campaign: CampaignCreate, current_user: dict = Depends(admin_required)):
    result = await db.mkt_campaigns.update_one({"id": campaign_id}, {"$set": campaign.model_dump()})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Campanha não encontrada")
    doc = await db.mkt_campaigns.find_one({"id": campaign_id}, {"_id": 0})
    return await _campaign_response(doc)

@api_router.delete("/marketing/campaigns/{campaign_id}")
async def delete_campaign(campaign_id: str, current_user: dict = Depends(admin_required)):
    result = await db.mkt_campaigns.delete_one({"id": campaign_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Campanha não encontrada")
    return {"message": "Campanha eliminada com sucesso"}

# ==================== MARKETING — CALENDÁRIO DE CONTEÚDOS ====================

class PostCreate(BaseModel):
    title: str
    channel: str = "instagram"      # instagram | facebook | tiktok | google | website | outro
    company_id: Optional[str] = None
    scheduled_date: Optional[str] = None  # AAAA-MM-DD (None = ideia sem data)
    scheduled_time: Optional[str] = None  # HH:MM
    status: str = "ideia"           # ideia | agendado | publicado
    content: Optional[str] = None

class PostResponse(BaseModel):
    id: str
    title: str
    channel: str
    company_id: Optional[str] = None
    company_name: Optional[str] = None
    scheduled_date: Optional[str] = None
    scheduled_time: Optional[str] = None
    status: str
    content: Optional[str] = None
    created_at: str

async def _post_response(doc: dict) -> PostResponse:
    company_name = None
    if doc.get("company_id"):
        company = await db.companies.find_one({"id": doc["company_id"]}, {"_id": 0, "name": 1})
        company_name = company["name"] if company else None
    return PostResponse(**doc, company_name=company_name)

@api_router.get("/marketing/posts", response_model=List[PostResponse])
async def list_posts(status: Optional[str] = None, channel: Optional[str] = None,
                     company_id: Optional[str] = None, current_user: dict = Depends(admin_required)):
    query = {}
    if status:
        query["status"] = status
    if channel:
        query["channel"] = channel
    if company_id:
        query["company_id"] = company_id
    docs = await db.mkt_posts.find(query, {"_id": 0}).sort("scheduled_date", 1).to_list(2000)
    return [await _post_response(d) for d in docs]

@api_router.post("/marketing/posts", response_model=PostResponse)
async def create_post(post: PostCreate, current_user: dict = Depends(admin_required)):
    if post.company_id:
        company = await db.companies.find_one({"id": post.company_id}, {"_id": 0})
        if not company:
            raise HTTPException(status_code=404, detail="Empresa não encontrada")
    doc = {
        "id": str(uuid.uuid4()),
        **post.model_dump(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": current_user.get("user_id"),
    }
    await db.mkt_posts.insert_one(doc)
    return await _post_response(doc)

@api_router.put("/marketing/posts/{post_id}", response_model=PostResponse)
async def update_post(post_id: str, post: PostCreate, current_user: dict = Depends(admin_required)):
    result = await db.mkt_posts.update_one({"id": post_id}, {"$set": post.model_dump()})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Publicação não encontrada")
    doc = await db.mkt_posts.find_one({"id": post_id}, {"_id": 0})
    return await _post_response(doc)

@api_router.delete("/marketing/posts/{post_id}")
async def delete_post(post_id: str, current_user: dict = Depends(admin_required)):
    result = await db.mkt_posts.delete_one({"id": post_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Publicação não encontrada")
    return {"message": "Publicação eliminada com sucesso"}

# ==================== HEALTH CHECK ====================

@api_router.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.now(timezone.utc).isoformat()}

# Include the router in the main app
app.include_router(api_router)

# CORS: em produção definir CORS_ORIGINS com o(s) domínio(s) do frontend,
# separados por vírgula (ex.: https://rh.suaempresa.pt). Em dev fica '*'.
# Nota: com origens '*' não é permitido allow_credentials=True (o browser rejeita).
# Como a autenticação usa Bearer token no header (não cookies), isto é seguro.
cors_origins = [o.strip() for o in os.environ.get('CORS_ORIGINS', '*').split(',') if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_credentials='*' not in cors_origins,
    allow_origins=cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_event():
    """Initialize application on startup"""
    await ensure_master_admin_exists()

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()


if __name__ == "__main__":
    # Arranque direto para desenvolvimento: `python server.py`
    # Em produção (VPS) usar antes:
    #   uvicorn server:app --host 0.0.0.0 --port 8000 --workers 2
    import uvicorn
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=False)
