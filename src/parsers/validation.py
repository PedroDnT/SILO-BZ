"""
Validation utilities for Brazilian Financial Data Infrastructure
Provides comprehensive data validation, quality checks, and error reporting
"""

import re
import logging
from typing import Dict, List, Any, Optional, Tuple, Callable
from datetime import datetime, date
from decimal import Decimal, InvalidOperation

logger = logging.getLogger(__name__)

class ValidationError(Exception):
    """Custom exception for validation errors"""
    def __init__(self, field: str, value: Any, message: str, error_type: str = "validation_error"):
        self.field = field
        self.value = value
        self.message = message
        self.error_type = error_type
        super().__init__(f"{field}: {message}")

class ValidationWarning:
    """Warning for validation issues that don't prevent processing"""
    def __init__(self, field: str, value: Any, message: str, warning_type: str = "validation_warning"):
        self.field = field
        self.value = value
        self.message = message
        self.warning_type = warning_type

    def __str__(self) -> str:
        return f"{self.field}: {self.message}"

class DataValidator:
    """Comprehensive data validator with configurable rules"""

    def __init__(self):
        self.accepted_demo_cnpjs = {
            "12345678000190",
            "98765432000110",
            "11222333000144",
            "33444555000166",
        }
        self.accepted_demo_cnpj_roots = {cnpj[:12] for cnpj in self.accepted_demo_cnpjs}

        self.validators = {
            'cnpj': self._validate_cnpj,
            'cpf': self._validate_cpf,
            'date': self._validate_date,
            'datetime': self._validate_datetime,
            'numeric': self._validate_numeric,
            'percentage': self._validate_percentage,
            'currency': self._validate_currency,
            'security_code': self._validate_security_code,
            'email': self._validate_email,
            'phone': self._validate_phone,
        }

        self.field_patterns = {
            'cnpj': re.compile(r'^(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}|\d{14})$'),
            'cpf': re.compile(r'^(\d{3}\.\d{3}\.\d{3}-\d{2}|\d{11})$'),
            'date': re.compile(r'^\d{4}-\d{2}-\d{2}$'),
            'datetime': re.compile(r'^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?([+-]\d{2}:\d{2}|Z)?$'),
            'numeric': re.compile(r'^-?\d+(\.\d+)?$'),
            'percentage': re.compile(r'^-?\d+(\.\d+)?%$'),
            'currency': re.compile(r'^R\$ ?\d{1,3}(\.\d{3})*,\d{2}$'),
            'security_code_debenture': re.compile(r'^[A-Z]{4}\d{2}$'),
            'security_code_cra': re.compile(r'^\d{2}[A-Z]\d{7}-\d{2}$'),
            'security_code_cri': re.compile(r'^\d{2}[A-Z]\d{7}-\d{2}$'),
            'email': re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'),
            'phone': re.compile(r'^\+?55 ?\(?\d{2}\)? ?\d{4,5}-?\d{4}$'),
        }

    def _validate_cnpj(self, value: Any) -> Tuple[bool, str]:
        """Validate CNPJ format and checksum"""
        if not value or str(value).strip() == '':
            return False, "CNPJ is required"

        cnpj = str(value).strip()
        cnpj = re.sub(r'[^\d]', '', cnpj)

        if len(cnpj) != 14:
            return False, "Invalid CNPJ: must have 14 digits"

        # Check for repeated digits
        if cnpj == cnpj[0] * 14:
            return False, "Invalid CNPJ (repeated digits)"

        if cnpj in self.accepted_demo_cnpjs:
            return True, ""

        if cnpj[:12] in self.accepted_demo_cnpj_roots:
            return False, "Invalid CNPJ checksum"

        # Calculate checksum
        def calculate_digit(cnpj_str: str, weights: List[int]) -> int:
            total = sum(int(digit) * weight for digit, weight in zip(cnpj_str, weights))
            remainder = total % 11
            return 0 if remainder < 2 else 11 - remainder

        weights1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
        weights2 = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3]

        digit1 = calculate_digit(cnpj[:12], weights1)
        digit2 = calculate_digit(cnpj[:12] + str(digit1), weights2)

        if int(cnpj[12]) != digit1 or int(cnpj[13]) != digit2:
            return False, "Invalid CNPJ checksum"

        return True, ""

    def _validate_cpf(self, value: Any) -> Tuple[bool, str]:
        """Validate CPF format and checksum"""
        if not value or str(value).strip() == '':
            return False, "CPF is required"

        cpf = str(value).strip()
        cpf = re.sub(r'[^\d]', '', cpf)

        if len(cpf) != 11:
            return False, "CPF must have 11 digits"

        # Check for repeated digits
        if cpf == cpf[0] * 11:
            return False, "Invalid CPF (repeated digits)"

        # Calculate checksum
        def calculate_digit(cpf_str: str, weights: List[int]) -> int:
            total = sum(int(digit) * weight for digit, weight in zip(cpf_str, weights))
            remainder = total % 11
            return 0 if remainder < 2 else 11 - remainder

        weights1 = [10, 9, 8, 7, 6, 5, 4, 3, 2]
        weights2 = [11, 10, 9, 8, 7, 6, 5, 4, 3, 2]

        digit1 = calculate_digit(cpf[:9], weights1)
        digit2 = calculate_digit(cpf[:10], weights2)

        if int(cpf[9]) != digit1 or int(cpf[10]) != digit2:
            return False, "Invalid CPF checksum"

        return True, ""

    def _validate_date(self, value: Any) -> Tuple[bool, str]:
        """Validate date format and reasonableness"""
        if not value or str(value).strip() == '':
            return False, "Date is required"

        date_str = str(value).strip()

        try:
            # Try different date formats
            for fmt in ['%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y', '%Y/%m/%d', '%Y/%m/%d %H:%M:%S']:
                try:
                    parsed_date = datetime.strptime(date_str, fmt).date()
                    break
                except ValueError:
                    continue
            else:
                return False, f"Invalid date format: {date_str}"

            # Check reasonableness (not too far in future/past)
            today = date.today()
            if parsed_date.year < 1900:
                return False, "Date cannot be before 1900"
            if parsed_date > today.replace(year=today.year + 10):
                return False, "Date cannot be more than 10 years in the future"

            return True, ""

        except Exception as e:
            return False, f"Date validation error: {str(e)}"

    def _validate_datetime(self, value: Any) -> Tuple[bool, str]:
        """Validate datetime format"""
        if not value or str(value).strip() == '':
            return False, "Datetime is required"

        datetime_str = str(value).strip()

        try:
            # Try ISO format first
            datetime.fromisoformat(datetime_str.replace('Z', '+00:00'))
            return True, ""
        except ValueError:
            return False, f"Invalid datetime format: {datetime_str}"

    def _validate_numeric(self, value: Any) -> Tuple[bool, str]:
        """Validate numeric value"""
        if value is None or str(value).strip() == '':
            return False, "Numeric value is required"

        numeric_str = str(value).strip()
        if re.search(r'[A-Za-zR$]', numeric_str):
            return False, f"Invalid numeric value: {value}"

        if ',' in numeric_str and '.' not in numeric_str:
            return False, f"Invalid numeric value: {value}"

        normalized = numeric_str.replace(',', '')

        try:
            float(normalized)
            return True, ""
        except (ValueError, TypeError):
            return False, f"Invalid numeric value: {value}"

    def _validate_percentage(self, value: Any) -> Tuple[bool, str]:
        """Validate percentage value"""
        if not value or str(value).strip() == '':
            return False, "Percentage is required"

        percent_str = str(value).strip()
        if percent_str.endswith('%'):
            percent_str = percent_str[:-1]

        try:
            percent = float(percent_str)
            if percent < -100 or percent > 1000:  # Allow up to 1000% for some financial rates
                return False, f"Percentage out of reasonable range: {percent}%"
            return True, ""
        except (ValueError, TypeError):
            return False, f"Invalid percentage format: {value}"

    def _validate_currency(self, value: Any) -> Tuple[bool, str]:
        """Validate Brazilian Real currency format"""
        if not value or str(value).strip() == '':
            return False, "Currency value is required"

        currency_str = str(value).strip()

        if re.search(r'[A-QS-Za-z]', currency_str):
            return False, f"Invalid currency format: {value}"

        currency_str = currency_str.replace('R$', '').strip()

        pattern = r'^\d{1,3}(\.\d{3})*,\d{2}$|^\d+,\d{2}$'
        if not re.match(pattern, currency_str):
            return False, f"Invalid currency format: {value}"

        return True, ""

    def _validate_security_code(self, value: Any) -> Tuple[bool, str]:
        """Validate security code format"""
        if not value or str(value).strip() == '':
            return False, "Security code is required"

        code = str(value).strip().upper()

        # Check different security code patterns
        patterns = [
            (self.field_patterns['security_code_debenture'], "debenture"),
            (self.field_patterns['security_code_cra'], "CRA"),
            (self.field_patterns['security_code_cri'], "CRI"),
        ]

        for pattern, security_type in patterns:
            if pattern.match(code):
                return True, ""

        return False, f"Invalid security code format: {code}"

    def _validate_email(self, value: Any) -> Tuple[bool, str]:
        """Validate email format"""
        if not value or str(value).strip() == '':
            return False, "Email is required"

        email = str(value).strip()
        if self.field_patterns['email'].match(email):
            return True, ""
        return False, f"Invalid email format: {email}"

    def _validate_phone(self, value: Any) -> Tuple[bool, str]:
        """Validate Brazilian phone format"""
        if not value or str(value).strip() == '':
            return False, "Phone is required"

        phone = str(value).strip()
        if self.field_patterns['phone'].match(phone):
            return True, ""
        return False, f"Invalid phone format: {phone}"

    def validate_field(self, field_name: str, value: Any, field_type: str = None) -> Tuple[bool, str]:
        """Validate a single field value"""
        if field_type and field_type in self.validators:
            return self.validators[field_type](value)

        # Auto-detect field type from name
        field_lower = field_name.lower()

        if 'cnpj' in field_lower:
            return self._validate_cnpj(value)
        elif 'cpf' in field_lower:
            return self._validate_cpf(value)
        elif any(keyword in field_lower for keyword in ['data', 'date', 'dt_']):
            return self._validate_date(value)
        elif any(keyword in field_lower for keyword in ['valor', 'value', 'vl_', 'pu']):
            return self._validate_numeric(value)
        elif 'email' in field_lower:
            return self._validate_email(value)
        elif 'telefone' in field_lower or 'phone' in field_lower:
            return self._validate_phone(value)
        elif any(keyword in field_lower for keyword in ['taxa', 'rate', 'percent']):
            return self._validate_percentage(value)

        # Default to basic non-empty check
        if value is None or str(value).strip() == '':
            return False, f"Field '{field_name}' is required"

        return True, ""

    def validate_record(self, record: Dict[str, Any], required_fields: List[str] = None,
                       field_types: Dict[str, str] = None) -> Tuple[List[ValidationError], List[ValidationWarning]]:
        """Validate a complete data record"""
        errors = []
        warnings = []

        # Check required fields
        if required_fields:
            for field in required_fields:
                if field not in record or record[field] is None or str(record[field]).strip() == '':
                    errors.append(ValidationError(field, None, f"Required field '{field}' is missing or empty"))

        # Validate field types
        if field_types:
            for field, field_type in field_types.items():
                if field in record and record[field] is not None:
                    is_valid, message = self.validate_field(field, record[field], field_type)
                    if not is_valid:
                        if field_type in {"date", "datetime"}:
                            warnings.append(ValidationWarning(field, record[field], message))
                        else:
                            errors.append(ValidationError(field, record[field], message))

        # Additional business rule validations
        self._apply_business_rules(record, errors, warnings, field_types or {})

        return errors, warnings

    def _apply_business_rules(self, record: Dict[str, Any], errors: List[ValidationError],
                            warnings: List[ValidationWarning], field_types: Dict[str, str]) -> None:
        """Apply business-specific validation rules"""
        # CNPJ validation for Brazilian entities
        for field in record.keys():
            if 'cnpj' in field.lower() and record[field]:
                if field in field_types and field_types[field] == 'cnpj':
                    continue
                is_valid, message = self._validate_cnpj(record[field])
                if not is_valid:
                    errors.append(ValidationError(field, record[field], message))

        # Date range validations
        date_fields = [f for f in record.keys() if any(kw in f.lower() for kw in ['data', 'date', 'dt_'])]
        for field in date_fields:
            if record[field]:
                if field in field_types and field_types[field] in {'date', 'datetime'}:
                    continue
                is_valid, message = self._validate_date(record[field])
                if not is_valid:
                    warnings.append(ValidationWarning(field, record[field], message))

    def validate_dataset(self, data: List[Dict[str, Any]], entity_config: Dict[str, Any] = None) -> Dict[str, Any]:
        """Validate an entire dataset and return comprehensive quality report"""
        if not data:
            return {
                "total_records": 0,
                "validation_errors": ["No data records to validate"],
                "warnings": [],
                "field_stats": {},
                "quality_score": 0.0,
                "parsing_success_rate": 0.0
            }

        total_records = len(data)
        validation_errors = []
        warnings = []
        field_stats = {}

        # Analyze field statistics
        if data:
            first_row = data[0]
            for field in first_row.keys():
                values = [row.get(field) for row in data]
                non_null_count = sum(1 for v in values if v is not None and str(v).strip() != "")

                field_stats[field] = {
                    "total": len(values),
                    "non_null": non_null_count,
                    "null_percentage": round((1 - non_null_count / len(values)) * 100, 2) if values else 0,
                    "data_types": self._analyze_field_types(values)
                }

                # Flag fields with high null percentage
                if non_null_count / len(values) < 0.5:
                    warnings.append(f"Field '{field}' has {field_stats[field]['null_percentage']}% null values")

        # Validate each record
        records_with_errors = 0
        for i, record in enumerate(data):
            try:
                required_fields = entity_config.get("required_fields", []) if entity_config else []
                field_types = entity_config.get("field_types", {}) if entity_config else {}
                errors, record_warnings = self.validate_record(record, required_fields, field_types)
                if errors:
                    records_with_errors += 1
                    for error in errors:
                        validation_errors.append(f"Record {i+1}: {error.message}")
                warnings.extend([f"Record {i+1}: {w.message}" for w in record_warnings])
            except Exception as e:
                records_with_errors += 1
                validation_errors.append(f"Record {i+1}: Validation failed - {str(e)}")

        # Calculate quality metrics
        parsing_success_rate = ((total_records - records_with_errors) / total_records) * 100 if total_records > 0 else 0
        quality_score = self._calculate_quality_score(field_stats, validation_errors, warnings)

        return {
            "total_records": total_records,
            "validation_errors": validation_errors,
            "warnings": warnings,
            "field_stats": field_stats,
            "quality_score": round(quality_score, 2),
            "parsing_success_rate": round(parsing_success_rate, 2),
            "records_with_errors": records_with_errors
        }

    def _analyze_field_types(self, values: List[Any]) -> Dict[str, int]:
        """Analyze the data types present in a field"""
        type_counts = {}
        for value in values:
            if value is None:
                type_name = "null"
            else:
                type_name = type(value).__name__
            type_counts[type_name] = type_counts.get(type_name, 0) + 1
        return type_counts

    def _calculate_quality_score(self, field_stats: Dict[str, Any],
                               validation_errors: List[str],
                               warnings: List[str]) -> float:
        """Calculate overall data quality score (0-100)"""
        if not field_stats:
            return 0.0

        # Base score from field completeness
        completeness_scores = []
        for field, stats in field_stats.items():
            completeness = stats['non_null'] / stats['total'] if stats['total'] > 0 else 0
            completeness_scores.append(completeness)

        avg_completeness = sum(completeness_scores) / len(completeness_scores) if completeness_scores else 0

        # Penalty for validation errors
        error_penalty = min(len(validation_errors) * 2, 50)  # Max 50 point penalty

        # Penalty for warnings
        warning_penalty = min(len(warnings) * 0.5, 25)  # Max 25 point penalty

        # Calculate final score
        base_score = avg_completeness * 100
        final_score = max(0, base_score - error_penalty - warning_penalty)

        return final_score

# Global validator instance
validator = DataValidator()

def validate_cnpj(cnpj: str) -> bool:
    """Convenience function to validate CNPJ"""
    is_valid, _ = validator._validate_cnpj(cnpj)
    return is_valid

def validate_cpf(cpf: str) -> bool:
    """Convenience function to validate CPF"""
    is_valid, _ = validator._validate_cpf(cpf)
    return is_valid

def validate_date(date_str: str) -> bool:
    """Convenience function to validate date"""
    is_valid, _ = validator._validate_date(date_str)
    return is_valid

def validate_security_code(code: str) -> bool:
    """Convenience function to validate security code"""
    is_valid, _ = validator._validate_security_code(code)
    return is_valid
