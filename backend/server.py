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
from datetime import datetime, timezone, timedelta
import jwt
import bcrypt
import shutil
import re
import secrets
import hashlib
import asyncio

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

# Password Reset Configuration
RESET_TOKEN_EXPIRATION_HOURS = 1

# Resend Email Configuration
RESEND_API_KEY = os.environ.get('RESEND_API_KEY')
SENDER_EMAIL = os.environ.get('SENDER_EMAIL', 'onboarding@resend.dev')
FRONTEND_URL = os.environ.get('FRONTEND_URL', 'https://github-rh-deploy.preview.emergentagent.com')

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

def generate_reset_token() -> str:
    """Generate a secure random token for password reset"""
    return secrets.token_urlsafe(32)

def hash_reset_token(token: str) -> str:
    """Hash the reset token using SHA256 for storage"""
    return hashlib.sha256(token.encode('utf-8')).hexdigest()

def get_password_reset_email_html(user_name: str, reset_link: str) -> str:
    """Generate HTML email template for password reset"""
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
    </head>
    <body style="margin: 0; padding: 0; font-family: Arial, Helvetica, sans-serif; background-color: #f4f4f4;">
        <table role="presentation" style="width: 100%; border-collapse: collapse;">
            <tr>
                <td style="padding: 40px 0;">
                    <table role="presentation" style="width: 600px; margin: 0 auto; background-color: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.1);">
                        <!-- Header -->
                        <tr>
                            <td style="background-color: #1a365d; padding: 30px; text-align: center;">
                                <h1 style="color: #ffffff; margin: 0; font-size: 24px;">RH grupo Lisbonb</h1>
                            </td>
                        </tr>
                        <!-- Content -->
                        <tr>
                            <td style="padding: 40px 30px;">
                                <h2 style="color: #1a365d; margin: 0 0 20px 0; font-size: 20px;">Redefinição de Palavra-passe</h2>
                                <p style="color: #4a5568; font-size: 16px; line-height: 1.6; margin: 0 0 20px 0;">
                                    Olá <strong>{user_name}</strong>,
                                </p>
                                <p style="color: #4a5568; font-size: 16px; line-height: 1.6; margin: 0 0 20px 0;">
                                    Recebemos um pedido para redefinir a palavra-passe da sua conta. 
                                    Clique no botão abaixo para criar uma nova palavra-passe:
                                </p>
                                <table role="presentation" style="margin: 30px auto;">
                                    <tr>
                                        <td style="background-color: #1a365d; border-radius: 6px;">
                                            <a href="{reset_link}" style="display: inline-block; padding: 14px 30px; color: #ffffff; text-decoration: none; font-weight: bold; font-size: 16px;">
                                                Redefinir Palavra-passe
                                            </a>
                                        </td>
                                    </tr>
                                </table>
                                <p style="color: #718096; font-size: 14px; line-height: 1.6; margin: 20px 0 0 0;">
                                    Este link é válido por <strong>1 hora</strong>. Se não solicitou esta alteração, 
                                    pode ignorar este email em segurança.
                                </p>
                                <p style="color: #718096; font-size: 14px; line-height: 1.6; margin: 20px 0 0 0;">
                                    Se o botão não funcionar, copie e cole o link abaixo no seu navegador:
                                </p>
                                <p style="color: #4299e1; font-size: 12px; word-break: break-all; margin: 10px 0 0 0;">
                                    {reset_link}
                                </p>
                            </td>
                        </tr>
                        <!-- Footer -->
                        <tr>
                            <td style="background-color: #f7fafc; padding: 20px 30px; text-align: center; border-top: 1px solid #e2e8f0;">
                                <p style="color: #a0aec0; font-size: 12px; margin: 0;">
                                    © 2024 RH grupo Lisbonb. Todos os direitos reservados.
                                </p>
                                <p style="color: #a0aec0; font-size: 12px; margin: 10px 0 0 0;">
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

async def send_password_reset_email(email: str, user_name: str, reset_token: str) -> bool:
    """Send password reset email using Resend"""
    if not RESEND_AVAILABLE or not RESEND_API_KEY:
        logger.warning("Resend not configured. Password reset email not sent.")
        return False
    
    reset_link = f"{FRONTEND_URL}/redefinir-senha?token={reset_token}"
    html_content = get_password_reset_email_html(user_name, reset_link)
    
    params = {
        "from": SENDER_EMAIL,
        "to": [email],
        "subject": "Redefinição de Palavra-passe - RH grupo Lisbonb",
        "html": html_content
    }
    
    try:
        # Run sync SDK in thread to keep FastAPI non-blocking
        email_response = await asyncio.to_thread(resend.Emails.send, params)
        logger.info(f"Password reset email sent to {email}, ID: {email_response.get('id')}")
        return True
    except Exception as e:
        logger.error(f"Failed to send password reset email: {str(e)}")
        return False

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

class LocationResponse(BaseModel):
    id: str
    name: str
    company_id: str
    company_name: Optional[str] = None
    address: Optional[str] = None

class EmployeeCreate(BaseModel):
    name: str
    email: EmailStr
    password: str
    company_id: str
    location_id: str
    position: str
    contract_type: str
    start_date: str
    vacation_days: int = 22
    observations: Optional[str] = None

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

class EmployeeResponse(BaseModel):
    id: str
    user_id: str
    name: str
    email: str
    company_id: str
    company_name: Optional[str] = None
    location_id: str
    location_name: Optional[str] = None
    position: str
    contract_type: str
    start_date: str
    vacation_days: int
    vacation_days_used: int = 0
    vacation_days_available: int = 0
    observations: Optional[str] = None
    created_at: str

class TimeRecordCreate(BaseModel):
    record_type: str  # entrada or saida

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

# ==================== VACATION CALCULATION ====================

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
            days = (effective_end - effective_start).days + 1
            total_days += days
    
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
    """Require admin role"""
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Acesso negado. Apenas administradores.")
    return current_user

async def ensure_master_admin_exists():
    """Ensure master admin exists in database using environment variables"""
    if not MASTER_ADMIN_PASSWORD_HASH:
        logger.warning("ADMIN_PASSWORD_HASH not configured. Master admin will not be auto-created.")
        return
    
    existing = await db.users.find_one({"email": MASTER_ADMIN_EMAIL})
    if not existing:
        admin_doc = {
            "id": str(uuid.uuid4()),
            "email": MASTER_ADMIN_EMAIL,
            "password": MASTER_ADMIN_PASSWORD_HASH,
            "name": "Administrador Principal",
            "role": "admin",
            "employee_id": None,
            "must_change_password": False,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        await db.users.insert_one(admin_doc)
        logger.info(f"Master admin created: {MASTER_ADMIN_EMAIL}")

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
            "must_change_password": must_change_password
        }
    }

@api_router.get("/auth/me", response_model=UserResponse)
async def get_me(current_user: dict = Depends(get_current_user)):
    """Get current user information"""
    user = await db.users.find_one({"id": current_user["user_id"]}, {"_id": 0, "password": 0})
    if not user:
        raise HTTPException(status_code=404, detail="Utilizador não encontrado")
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
        if v not in ['admin', 'gerente']:
            raise ValueError("Role deve ser 'admin' ou 'gerente'")
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
        {"role": {"$in": ["admin", "gerente"]}, "email": {"$ne": MASTER_ADMIN_EMAIL}},
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
    
    return [LocationResponse(**l) for l in locations]

@api_router.put("/locations/{location_id}", response_model=LocationResponse)
async def update_location(location_id: str, location: LocationCreate, current_user: dict = Depends(admin_required)):
    result = await db.locations.update_one(
        {"id": location_id},
        {"$set": {"name": location.name, "company_id": location.company_id, "address": location.address}}
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
    
    location = await db.locations.find_one({"id": employee.location_id}, {"_id": 0})
    if not location:
        raise HTTPException(status_code=404, detail="Local não encontrado")
    
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

@api_router.put("/employees/{employee_id}", response_model=EmployeeResponse)
async def update_employee(employee_id: str, employee: EmployeeUpdate, current_user: dict = Depends(admin_required)):
    update_data = {k: v for k, v in employee.model_dump().items() if v is not None}
    
    if not update_data:
        raise HTTPException(status_code=400, detail="Nenhum dado para atualizar")
    
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

class ResetPasswordRequest(BaseModel):
    new_password: str

    @field_validator('new_password')
    @classmethod
    def validate_new_password(cls, v):
        is_valid, message = validate_password_strength(v)
        if not is_valid:
            raise ValueError(message)
        return v

@api_router.post("/employees/{employee_id}/reset-password")
async def reset_employee_password(employee_id: str, request: ResetPasswordRequest, current_user: dict = Depends(admin_required)):
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
    
    record_id = str(uuid.uuid4())
    record_doc = {
        "id": record_id,
        "employee_id": employee_id,
        "record_type": record.record_type,
        "time": datetime.now(timezone.utc).isoformat(),
        "corrected": False,
        "correction_history": []
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
    
    # Filter by company (admin only)
    if company_id and current_user.get("role") == "admin":
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

# ==================== LEAVE REQUEST ROUTES ====================

@api_router.post("/leave-requests", response_model=LeaveRequestResponse)
async def create_leave_request(request: LeaveRequestCreate, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "colaborador":
        raise HTTPException(status_code=403, detail="Apenas colaboradores podem criar pedidos")
    
    employee_id = current_user.get("employee_id")
    if not employee_id:
        raise HTTPException(status_code=400, detail="Utilizador não associado a colaborador")
    
    # Validate leave type
    valid_types = ["ferias", "falta", "doenca", "folga"]
    if request.leave_type not in valid_types:
        raise HTTPException(status_code=400, detail=f"Tipo inválido. Use: {', '.join(valid_types)}")
    
    request_id = str(uuid.uuid4())
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
    
    # Filter by company (admin only)
    if company_id and current_user.get("role") == "admin":
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
    
    return [LeaveRequestResponse(**r) for r in requests]

class LeaveRequestResponseModel(BaseModel):
    status: str
    response: Optional[str] = None

@api_router.put("/leave-requests/{request_id}/respond")
async def respond_leave_request(
    request_id: str,
    data: LeaveRequestResponseModel,
    current_user: dict = Depends(admin_required)
):
    if data.status not in ["aprovado", "recusado"]:
        raise HTTPException(status_code=400, detail="Status inválido. Use 'aprovado' ou 'recusado'")
    
    leave_request = await db.leave_requests.find_one({"id": request_id}, {"_id": 0})
    if not leave_request:
        raise HTTPException(status_code=404, detail="Pedido não encontrado")
    
    await db.leave_requests.update_one(
        {"id": request_id},
        {"$set": {"status": data.status, "admin_response": data.response}}
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
    
    updated = await db.leave_requests.find_one({"id": request_id}, {"_id": 0})
    updated["employee_name"] = employee["name"] if employee else None
    return LeaveRequestResponse(**updated)

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
    
    # Notify if admin uploaded for employee
    if current_user.get("role") == "admin":
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
async def get_admin_dashboard(company_id: Optional[str] = None, current_user: dict = Depends(admin_required)):
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
    
    return {
        "total_employees": total_employees,
        "total_companies": total_companies,
        "pending_requests": pending_requests,
        "today_records": today_records,
        "employees_by_company": employees_by_company,
        "recent_requests": recent_requests
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
    
    # Filter by company for admin
    if company_id and current_user.get("role") == "admin":
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
    
    return leaves

# ==================== HEALTH CHECK ====================

@api_router.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.now(timezone.utc).isoformat()}

# Include the router in the main app
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
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
