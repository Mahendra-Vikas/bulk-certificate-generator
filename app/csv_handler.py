"""
CSV Handler Module
Handles reading and searching student data from a CSV export
"""

import csv
import os
from pathlib import Path
from typing import Optional, List, Dict, Iterable


class CSVHandler:
    """Handle CSV operations for student data"""
    
    def __init__(self, csv_path: str = "students.csv", management_csv_path: str = "management.csv"):
        """
        Initialize CSV handler
        
        Args:
            csv_path: Path to the CSV file containing student data
            management_csv_path: Path to the CSV file containing management team data
        """
        project_root = Path(__file__).resolve().parents[1]
        normalized = (csv_path or "").replace("\\", "/")
        candidate = Path(normalized)
        if not candidate.is_absolute():
            candidate = project_root / candidate

        self.csv_path = str(candidate)
        
        normalized_mgmt = (management_csv_path or "").replace("\\", "/")
        candidate_mgmt = Path(normalized_mgmt)
        if not candidate_mgmt.is_absolute():
            candidate_mgmt = project_root / candidate_mgmt
        
        self.management_csv_path = str(candidate_mgmt)
        self._project_root = project_root

    @staticmethod
    def _normalize_key(key: str) -> str:
        return "".join(ch for ch in (key or "").strip().lower() if ch.isalnum() or ch == "_")

    @classmethod
    def _get_first(cls, row: Dict[str, str], keys: Iterable[str]) -> str:
        normalized_row = {cls._normalize_key(k): v for k, v in row.items()}
        for key in keys:
            value = normalized_row.get(cls._normalize_key(key))
            if value is not None:
                return str(value)
        return ""

    @staticmethod
    def _normalize_name(value: str) -> str:
        # Collapse internal whitespace and normalize case.
        return " ".join((value or "").strip().lower().split())

    @staticmethod
    def _normalize_student_id(value: str) -> str:
        # Keep IDs as strings; remove leading/trailing whitespace.
        return (value or "").strip()

    def normalize_student(self, row: Dict[str, str]) -> Dict[str, str]:
        """Return a canonical student dict regardless of CSV header variations."""
        return {
            "Name": self._get_first(row, ["Name", "Full Name", "Student Name"]),
            "Student_Id": self._get_first(row, ["Student_Id", "Student ID", "StudentId", "Student_Id "]),
            "Email_id": self._get_first(row, ["Email_id", "Email id", "Email", "Email ID", "Email Address"]),
            "Course": self._get_first(row, ["Course", "Program", "Branch"]),
            "Code": self._get_first(row, ["Code", "Workshop", "Event", "Batch"]),
        }
    
    def normalize_management(self, row: Dict[str, str]) -> Dict[str, str]:
        """Return a canonical management dict regardless of CSV header variations."""
        return {
            "Name": self._get_first(row, ["Name", "Full Name"]),
            "Student_Id": self._get_first(row, ["Student_Id", "Student ID", "StudentId", "Mgmt_Id"]),
            "Email_id": self._get_first(row, ["Email_id", "Email id", "Email", "Email ID", "Email Address"]),
            "Course": self._get_first(row, ["Course", "Program", "Branch"]),
            "Position": self._get_first(row, ["Position", "Title", "Role"]),
        }
        
    def get_all_students(self) -> List[Dict[str, str]]:
        """
        Read all students from CSV file
        
        Returns:
            List of dictionaries containing student data
            
        Raises:
            FileNotFoundError: If CSV file doesn't exist
        """
        if not os.path.exists(self.csv_path):
            # Backward-compatible fallbacks (older deployments used data/students.csv)
            fallbacks = [
                str(self._project_root / "students.csv"),
                str(self._project_root / "data" / "students.csv"),
            ]
            for candidate in fallbacks:
                if os.path.exists(candidate):
                    self.csv_path = candidate
                    break
            else:
                raise FileNotFoundError(f"CSV file not found: {self.csv_path}")
        
        students: List[Dict[str, str]] = []
        # Use utf-8-sig to tolerate CSVs saved with a BOM (common with Excel/Forms exports)
        with open(self.csv_path, 'r', encoding='utf-8-sig', newline='') as file:
            reader = csv.DictReader(file)
            for row in reader:
                students.append(self.normalize_student(row))
        
        return students
    
    def find_student_by_name_and_id(self, name: str, student_id: str) -> Optional[Dict[str, str]]:
        """
        Find a student by their name and student ID
        
        Args:
            name: The student's name to search for
            student_id: The student ID to search for
            
        Returns:
            Dictionary containing student data if found, None otherwise
        """
        students = self.get_all_students()
        
        # Normalize inputs for comparison
        name_normalized = self._normalize_name(name)
        student_id_normalized = self._normalize_student_id(student_id)
        
        for student in students:
            student_name = self._normalize_name(student.get('Name', ''))
            student_sid = self._normalize_student_id(student.get('Student_Id', ''))
            
            # Match both name and student ID
            if student_name == name_normalized and student_sid == student_id_normalized:
                return student
        
        return None
    
    def generate_certificate_id(self, student_id: str, student_name: str = None) -> str:
        """
        Generate a certificate ID from student name or ID
        
        Args:
            student_id: The student's ID (fallback)
            student_name: The student's name (preferred for filename)
            
        Returns:
            Certificate ID (name-based if available, otherwise ID-based)
        """
        # Use student name if provided, sanitize it for filename
        if student_name:
            # Sanitize name: remove special chars, replace spaces with underscores
            sanitized_name = "".join(c if c.isalnum() or c == " " else "" for c in student_name)
            sanitized_name = sanitized_name.strip().replace(" ", "_")
            if sanitized_name:
                return sanitized_name
        
        # Fallback to ID-based format
        prefix = os.getenv("CERTIFICATE_ID_PREFIX", "CERT")
        return f"{prefix}-{student_id}"
    
    def validate_csv_structure(self) -> bool:
        """
        Validate that CSV has required columns
        
        Returns:
            True if CSV structure is valid, False otherwise
        """
        required_columns = {'Name', 'Student_Id'}
        
        try:
            students = self.get_all_students()
            if not students:
                return False
            
            first_row_keys = set(students[0].keys())
            return required_columns.issubset(first_row_keys)
            
        except Exception:
            return False
    
    def get_all_management(self) -> List[Dict[str, str]]:
        """
        Read all management team members from management CSV file
        
        Returns:
            List of dictionaries containing management data
            
        Raises:
            FileNotFoundError: If management CSV file doesn't exist
        """
        if not os.path.exists(self.management_csv_path):
            raise FileNotFoundError(f"Management CSV file not found: {self.management_csv_path}")
        
        management: List[Dict[str, str]] = []
        with open(self.management_csv_path, 'r', encoding='utf-8-sig', newline='') as file:
            reader = csv.DictReader(file)
            for row in reader:
                management.append(self.normalize_management(row))
        
        return management
    
    def find_management_by_name(self, name: str) -> Optional[Dict[str, str]]:
        """
        Find a management team member by name
        
        Args:
            name: The person's name to search for
            
        Returns:
            Dictionary containing management data if found, None otherwise
        """
        try:
            management = self.get_all_management()
        except FileNotFoundError:
            return None
        
        name_normalized = self._normalize_name(name)
        
        for person in management:
            person_name = self._normalize_name(person.get('Name', ''))
            if person_name == name_normalized:
                return person
        
        return None
    
    def find_management_by_name_and_id(self, name: str, mgmt_id: str) -> Optional[Dict[str, str]]:
        """
        Find a management team member by name and ID
        
        Args:
            name: The person's name to search for
            mgmt_id: The management ID to search for
            
        Returns:
            Dictionary containing management data if found, None otherwise
        """
        try:
            management = self.get_all_management()
        except FileNotFoundError:
            return None
        
        name_normalized = self._normalize_name(name)
        mgmt_id_normalized = self._normalize_student_id(mgmt_id)
        
        for person in management:
            person_name = self._normalize_name(person.get('Name', ''))
            person_id = self._normalize_student_id(person.get('Student_Id', ''))
            
            if person_name == name_normalized and person_id == mgmt_id_normalized:
                return person
        
        return None
    
    def generate_management_certificate_id(self, mgmt_id: str, person_name: str = None) -> str:
        """
        Generate a certificate ID for management from name or ID
        
        Args:
            mgmt_id: The management ID (fallback)
            person_name: The person's name (preferred)
            
        Returns:
            Certificate ID (name-based if available, otherwise ID-based)
        """
        # Use person name if provided, sanitize it for filename
        if person_name:
            # Sanitize name: remove special chars, replace spaces with underscores
            sanitized_name = "".join(c if c.isalnum() or c == " " else "" for c in person_name)
            sanitized_name = sanitized_name.strip().replace(" ", "_")
            if sanitized_name:
                return sanitized_name
        
        # Fallback to ID-based format
        prefix = os.getenv("MANAGEMENT_CERT_ID_PREFIX", "CERT-MGMT")
        return f"{prefix}-{mgmt_id}"

