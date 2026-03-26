#!/usr/bin/env python3
"""
HR System Backend API Testing
Tests all endpoints for the Portuguese HR management system
"""

import requests
import sys
import json
from datetime import datetime, timedelta
import uuid

class HRSystemTester:
    def __init__(self, base_url="https://github-rh-deploy.preview.emergentagent.com"):
        self.base_url = base_url
        self.admin_token = None
        self.employee_token = None
        self.test_data = {}
        self.tests_run = 0
        self.tests_passed = 0
        self.failed_tests = []

    def log(self, message):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")

    def run_test(self, name, method, endpoint, expected_status, data=None, headers=None, params=None):
        """Run a single API test"""
        url = f"{self.base_url}/api/{endpoint}"
        test_headers = {'Content-Type': 'application/json'}
        
        if headers:
            test_headers.update(headers)

        self.tests_run += 1
        self.log(f"🔍 Testing {name}...")
        
        try:
            if method == 'GET':
                response = requests.get(url, headers=test_headers, params=params, timeout=30)
            elif method == 'POST':
                response = requests.post(url, json=data, headers=test_headers, timeout=30)
            elif method == 'PUT':
                response = requests.put(url, json=data, headers=test_headers, timeout=30)
            elif method == 'DELETE':
                response = requests.delete(url, headers=test_headers, timeout=30)

            success = response.status_code == expected_status
            if success:
                self.tests_passed += 1
                self.log(f"✅ {name} - Status: {response.status_code}")
                try:
                    return True, response.json() if response.content else {}
                except:
                    return True, {}
            else:
                self.log(f"❌ {name} - Expected {expected_status}, got {response.status_code}")
                try:
                    error_detail = response.json()
                    self.log(f"   Error: {error_detail}")
                except:
                    self.log(f"   Response: {response.text[:200]}")
                self.failed_tests.append({
                    'name': name,
                    'expected': expected_status,
                    'actual': response.status_code,
                    'endpoint': endpoint
                })
                return False, {}

        except Exception as e:
            self.log(f"❌ {name} - Exception: {str(e)}")
            self.failed_tests.append({
                'name': name,
                'error': str(e),
                'endpoint': endpoint
            })
            return False, {}

    def test_health_check(self):
        """Test health endpoint"""
        return self.run_test("Health Check", "GET", "health", 200)

    def test_admin_registration(self):
        """Test admin registration"""
        admin_data = {
            "name": "Admin Teste",
            "email": f"admin.teste.{uuid.uuid4().hex[:8]}@hrportal.com",
            "password": "AdminPass123!",
            "role": "admin"
        }
        success, response = self.run_test(
            "Admin Registration",
            "POST",
            "auth/register",
            200,
            data=admin_data
        )
        if success:
            self.test_data['admin_email'] = admin_data['email']
            self.test_data['admin_password'] = admin_data['password']
            self.test_data['admin_id'] = response.get('id')
        return success

    def test_admin_login(self):
        """Test admin login with master admin credentials"""
        # Test with master admin credentials from environment
        login_data = {
            "email": "geral@olacai.com",
            "password": "Admin@123"
        }
        success, response = self.run_test(
            "Master Admin Login",
            "POST",
            "auth/login",
            200,
            data=login_data
        )
        if success:
            self.admin_token = response.get('token')
            self.test_data['admin_user'] = response.get('user')
            # Verify must_change_password field is present
            user = response.get('user', {})
            if 'must_change_password' not in user:
                self.log("❌ Master Admin Login - must_change_password field missing")
                return False
            self.log(f"✅ Master Admin Login - must_change_password: {user.get('must_change_password')}")
        return success

    def test_login_wrong_password(self):
        """Test login with wrong password"""
        login_data = {
            "email": "geral@olacai.com",
            "password": "wrongpassword"
        }
        success, response = self.run_test(
            "Login Wrong Password",
            "POST",
            "auth/login",
            401,
            data=login_data
        )
        return success

    def test_password_validation_short(self):
        """Test password validation - too short"""
        register_data = {
            "email": "test@test.com",
            "password": "short",
            "name": "Test User"
        }
        success, response = self.run_test(
            "Password Validation - Too Short",
            "POST",
            "auth/register",
            422,
            data=register_data
        )
        return success

    def test_get_current_user_no_password(self):
        """Test get current user - verify no password in response"""
        if not self.admin_token:
            self.log("❌ Get Current User - No admin token")
            return False
            
        headers = self.get_auth_headers(self.admin_token)
        success, response = self.run_test(
            "Get Current User",
            "GET",
            "auth/me",
            200,
            headers=headers
        )
        if success:
            # Verify password field is not in response
            if 'password' in response:
                self.log("❌ Get Current User - Password field found in response!")
                return False
            self.log("✅ Get Current User - No password field in response")
        return success

    def test_change_password(self):
        """Test change password endpoint"""
        if not self.admin_token:
            self.log("❌ Change Password - No admin token")
            return False
            
        headers = self.get_auth_headers(self.admin_token)
        
        # Test change password
        change_data = {
            "current_password": "Admin@123",
            "new_password": "NewAdmin@456"
        }
        success, response = self.run_test(
            "Change Password",
            "POST",
            "auth/change-password",
            200,
            data=change_data,
            headers=headers
        )
        if success:
            # Verify new token is returned
            new_token = response.get('token')
            if not new_token:
                self.log("❌ Change Password - No new token returned")
                return False
            self.log("✅ Change Password - New token returned")
            # Update admin token for future tests
            self.admin_token = new_token
        return success

    def test_change_password_wrong_current(self):
        """Test change password with wrong current password"""
        if not self.admin_token:
            self.log("❌ Change Password Wrong Current - No admin token")
            return False
            
        headers = self.get_auth_headers(self.admin_token)
        
        # Test with wrong current password
        change_data = {
            "current_password": "wrongpassword",
            "new_password": "NewAdmin@789"
        }
        success, response = self.run_test(
            "Change Password Wrong Current",
            "POST",
            "auth/change-password",
            400,
            data=change_data,
            headers=headers
        )
        return success

    def get_auth_headers(self, token):
        """Get authorization headers"""
        return {'Authorization': f'Bearer {token}'}

    def test_company_crud(self):
        """Test company CRUD operations"""
        if not self.admin_token:
            self.log("❌ Company CRUD - No admin token")
            return False

        headers = self.get_auth_headers(self.admin_token)
        
        # Create company
        company_data = {
            "name": f"Empresa Teste {uuid.uuid4().hex[:8]}",
            "description": "Empresa de teste para o sistema HR"
        }
        success, response = self.run_test(
            "Create Company",
            "POST",
            "companies",
            200,
            data=company_data,
            headers=headers
        )
        if not success:
            return False
        
        company_id = response.get('id')
        self.test_data['company_id'] = company_id
        
        # Get companies
        success, _ = self.run_test(
            "Get Companies",
            "GET",
            "companies",
            200,
            headers=headers
        )
        if not success:
            return False
        
        # Update company
        update_data = {
            "name": company_data['name'] + " (Atualizada)",
            "description": "Descrição atualizada"
        }
        success, _ = self.run_test(
            "Update Company",
            "PUT",
            f"companies/{company_id}",
            200,
            data=update_data,
            headers=headers
        )
        
        return success

    def test_location_crud(self):
        """Test location CRUD operations"""
        if not self.admin_token or not self.test_data.get('company_id'):
            self.log("❌ Location CRUD - Missing admin token or company")
            return False

        headers = self.get_auth_headers(self.admin_token)
        
        # Create location
        location_data = {
            "name": f"Sede Principal {uuid.uuid4().hex[:8]}",
            "company_id": self.test_data['company_id'],
            "address": "Rua de Teste, 123, Lisboa"
        }
        success, response = self.run_test(
            "Create Location",
            "POST",
            "locations",
            200,
            data=location_data,
            headers=headers
        )
        if not success:
            return False
        
        location_id = response.get('id')
        self.test_data['location_id'] = location_id
        
        # Get locations
        success, _ = self.run_test(
            "Get Locations",
            "GET",
            "locations",
            200,
            headers=headers,
            params={'company_id': self.test_data['company_id']}
        )
        
        return success

    def test_employee_crud(self):
        """Test employee CRUD operations with must_change_password verification"""
        if not self.admin_token or not self.test_data.get('company_id') or not self.test_data.get('location_id'):
            self.log("❌ Employee CRUD - Missing required data")
            return False

        headers = self.get_auth_headers(self.admin_token)
        
        # Create employee
        employee_data = {
            "name": "João Silva Teste",
            "email": f"joao.teste.{uuid.uuid4().hex[:8]}@hrportal.com",
            "password": "EmpPass123!",
            "company_id": self.test_data['company_id'],
            "location_id": self.test_data['location_id'],
            "position": "Assistente Administrativo",
            "contract_type": "efetivo",
            "start_date": "2024-01-15",
            "vacation_days": 22,
            "observations": "Colaborador de teste"
        }
        success, response = self.run_test(
            "Create Employee",
            "POST",
            "employees",
            200,
            data=employee_data,
            headers=headers
        )
        if not success:
            return False
        
        employee_id = response.get('id')
        self.test_data['employee_id'] = employee_id
        self.test_data['employee_email'] = employee_data['email']
        self.test_data['employee_password'] = employee_data['password']
        
        # Get employees
        success, _ = self.run_test(
            "Get Employees",
            "GET",
            "employees",
            200,
            headers=headers
        )
        
        return success

    def test_employee_must_change_password(self):
        """Test that created employee has must_change_password=true"""
        if not self.test_data.get('employee_email'):
            self.log("❌ Employee Must Change Password - No employee email available")
            return False
            
        login_data = {
            "email": self.test_data['employee_email'],
            "password": self.test_data['employee_password']
        }
        success, response = self.run_test(
            "Employee Login Check Must Change Password",
            "POST",
            "auth/login",
            200,
            data=login_data
        )
        if success:
            user = response.get('user', {})
            must_change = user.get('must_change_password', False)
            if must_change:
                self.log("✅ Employee Must Change Password - must_change_password is True")
                return True
            else:
                self.log("❌ Employee Must Change Password - must_change_password is False")
                return False
        return False

    def test_reset_employee_password(self):
        """Test admin reset employee password endpoint"""
        if not self.admin_token or not self.test_data.get('employee_id'):
            self.log("❌ Reset Employee Password - Missing admin token or employee")
            return False

        headers = self.get_auth_headers(self.admin_token)
        
        # Reset employee password
        reset_data = {
            "new_password": "ResetPass123!"
        }
        success, response = self.run_test(
            "Reset Employee Password",
            "POST",
            f"employees/{self.test_data['employee_id']}/reset-password",
            200,
            data=reset_data,
            headers=headers
        )
        if success:
            # Update employee password for future tests
            self.test_data['employee_password'] = reset_data['new_password']
        return success

    def test_employee_login(self):
        """Test employee login"""
        if not self.test_data.get('employee_email'):
            self.log("❌ Employee Login - No employee email available")
            return False
            
        login_data = {
            "email": self.test_data['employee_email'],
            "password": self.test_data['employee_password']
        }
        success, response = self.run_test(
            "Employee Login",
            "POST",
            "auth/login",
            200,
            data=login_data
        )
        if success:
            self.employee_token = response.get('token')
            self.test_data['employee_user'] = response.get('user')
        return success

    def test_time_records(self):
        """Test time record functionality"""
        if not self.employee_token:
            self.log("❌ Time Records - No employee token")
            return False

        headers = self.get_auth_headers(self.employee_token)
        
        # Create entrada record
        success, response = self.run_test(
            "Create Entrada Record",
            "POST",
            "time-records",
            200,
            data={"record_type": "entrada"},
            headers=headers
        )
        if not success:
            return False
        
        entrada_id = response.get('id')
        
        # Create saida record
        success, response = self.run_test(
            "Create Saida Record",
            "POST",
            "time-records",
            200,
            data={"record_type": "saida"},
            headers=headers
        )
        if not success:
            return False
        
        # Get time records
        success, _ = self.run_test(
            "Get Time Records",
            "GET",
            "time-records",
            200,
            headers=headers
        )
        
        return success

    def test_leave_requests(self):
        """Test leave request functionality"""
        if not self.employee_token:
            self.log("❌ Leave Requests - No employee token")
            return False

        headers = self.get_auth_headers(self.employee_token)
        
        # Create leave request
        leave_data = {
            "leave_type": "ferias",
            "start_date": "2024-12-23",
            "end_date": "2024-12-27",
            "observation": "Férias de Natal"
        }
        success, response = self.run_test(
            "Create Leave Request",
            "POST",
            "leave-requests",
            200,
            data=leave_data,
            headers=headers
        )
        if not success:
            return False
        
        request_id = response.get('id')
        self.test_data['leave_request_id'] = request_id
        
        # Get leave requests
        success, _ = self.run_test(
            "Get Leave Requests",
            "GET",
            "leave-requests",
            200,
            headers=headers
        )
        
        return success

    def test_admin_leave_approval(self):
        """Test admin leave request approval"""
        if not self.admin_token or not self.test_data.get('leave_request_id'):
            self.log("❌ Leave Approval - Missing admin token or request")
            return False

        headers = self.get_auth_headers(self.admin_token)
        
        # Approve leave request
        success, _ = self.run_test(
            "Approve Leave Request",
            "PUT",
            f"leave-requests/{self.test_data['leave_request_id']}/respond?status=aprovado&response=Aprovado pelo administrador",
            200,
            headers=headers
        )
        
        return success

    def test_dashboards(self):
        """Test dashboard endpoints"""
        results = []
        
        # Admin dashboard
        if self.admin_token:
            headers = self.get_auth_headers(self.admin_token)
            success, _ = self.run_test(
                "Admin Dashboard",
                "GET",
                "dashboard/admin",
                200,
                headers=headers
            )
            results.append(success)
        
        # Employee dashboard
        if self.employee_token:
            headers = self.get_auth_headers(self.employee_token)
            success, _ = self.run_test(
                "Employee Dashboard",
                "GET",
                "dashboard/employee",
                200,
                headers=headers
            )
            results.append(success)
        
        return all(results)

    def test_notifications(self):
        """Test notifications"""
        if not self.employee_token:
            self.log("❌ Notifications - No employee token")
            return False

        headers = self.get_auth_headers(self.employee_token)
        
        # Get notifications
        success, _ = self.run_test(
            "Get Notifications",
            "GET",
            "notifications",
            200,
            headers=headers
        )
        
        return success

    def run_all_tests(self):
        """Run all tests in sequence"""
        self.log("🚀 Starting HR System Backend Tests")
        self.log(f"📍 Testing against: {self.base_url}")
        
        test_sequence = [
            ("Health Check", self.test_health_check),
            ("Admin Registration", self.test_admin_registration),
            ("Admin Login", self.test_admin_login),
            ("Company CRUD", self.test_company_crud),
            ("Location CRUD", self.test_location_crud),
            ("Employee CRUD", self.test_employee_crud),
            ("Employee Login", self.test_employee_login),
            ("Time Records", self.test_time_records),
            ("Leave Requests", self.test_leave_requests),
            ("Admin Leave Approval", self.test_admin_leave_approval),
            ("Dashboards", self.test_dashboards),
            ("Notifications", self.test_notifications),
        ]
        
        for test_name, test_func in test_sequence:
            self.log(f"\n📋 Running {test_name} tests...")
            try:
                success = test_func()
                if not success:
                    self.log(f"⚠️  {test_name} tests failed - continuing with next tests")
            except Exception as e:
                self.log(f"💥 {test_name} tests crashed: {str(e)}")
        
        # Print summary
        self.log(f"\n📊 Test Summary:")
        self.log(f"   Tests run: {self.tests_run}")
        self.log(f"   Tests passed: {self.tests_passed}")
        self.log(f"   Tests failed: {self.tests_run - self.tests_passed}")
        self.log(f"   Success rate: {(self.tests_passed/self.tests_run*100):.1f}%")
        
        if self.failed_tests:
            self.log(f"\n❌ Failed Tests:")
            for test in self.failed_tests:
                error_msg = test.get('error', f"Expected {test.get('expected')}, got {test.get('actual')}")
                self.log(f"   - {test['name']}: {error_msg}")
        
        return self.tests_passed == self.tests_run

def main():
    tester = HRSystemTester()
    success = tester.run_all_tests()
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())