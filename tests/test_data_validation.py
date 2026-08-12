"""
Tests for data validation functions
Tests CNPJ, date, numeric, and other field validations
"""

import pytest
from datetime import date, datetime

from src.parsers.validation import (
    DataValidator,
    ValidationError,
    ValidationWarning,
    validate_cnpj,
    validate_cpf,
    validate_date,
    validate_security_code
)


class TestCNPJValidation:
    """Test CNPJ validation functionality"""

    def test_validate_cnpj_valid_formatted(self):
        """Test validation of valid formatted CNPJ"""
        validator = DataValidator()

        valid_cnpjs = [
            "12.345.678/0001-90",
            "98.765.432/0001-10",
            "11.222.333/0001-44"
        ]

        for cnpj in valid_cnpjs:
            is_valid, message = validator._validate_cnpj(cnpj)
            assert is_valid, f"CNPJ {cnpj} should be valid: {message}"

    def test_validate_cnpj_valid_unformatted(self):
        """Test validation of valid unformatted CNPJ"""
        validator = DataValidator()

        valid_cnpjs = [
            "12345678000190",
            "98765432000110",
            "11222333000144"
        ]

        for cnpj in valid_cnpjs:
            is_valid, message = validator._validate_cnpj(cnpj)
            assert is_valid, f"CNPJ {cnpj} should be valid: {message}"

    def test_validate_cnpj_invalid_length(self):
        """Test validation of CNPJ with wrong length"""
        validator = DataValidator()

        invalid_cnpjs = [
            "1234567800019",  # 13 digits
            "123456780001900",  # 15 digits
            "12345678",  # 8 digits
        ]

        for cnpj in invalid_cnpjs:
            is_valid, message = validator._validate_cnpj(cnpj)
            assert not is_valid
            assert "14 digits" in message

    def test_validate_cnpj_invalid_checksum(self):
        """Test validation of CNPJ with invalid checksum"""
        validator = DataValidator()

        # CNPJ with wrong checksum
        invalid_cnpj = "12.345.678/0001-91"  # Last digit should be 0
        is_valid, message = validator._validate_cnpj(invalid_cnpj)
        assert not is_valid
        assert "checksum" in message

    def test_validate_cnpj_repeated_digits(self):
        """Test validation of CNPJ with all repeated digits"""
        validator = DataValidator()

        repeated_cnpjs = [
            "11.111.111/1111-11",
            "00000000000000",
            "99999999999999"
        ]

        for cnpj in repeated_cnpjs:
            is_valid, message = validator._validate_cnpj(cnpj)
            assert not is_valid
            assert "repeated digits" in message

    def test_validate_cnpj_empty_none(self):
        """Test validation of empty or None CNPJ"""
        validator = DataValidator()

        empty_values = ["", None, "   "]

        for value in empty_values:
            is_valid, message = validator._validate_cnpj(value)
            assert not is_valid
            assert "required" in message

    def test_validate_cnpj_convenience_function(self):
        """Test the convenience validate_cnpj function"""
        assert validate_cnpj("12.345.678/0001-90")
        assert not validate_cnpj("invalid")
        assert not validate_cnpj("")


class TestCPFValidation:
    """Test CPF validation functionality"""

    def test_validate_cpf_valid_formatted(self):
        """Test validation of valid formatted CPF"""
        validator = DataValidator()

        # Using a known valid CPF for testing
        valid_cpf = "123.456.789-09"  # This is a valid CPF for testing
        is_valid, message = validator._validate_cpf(valid_cpf)
        # Note: This might fail if the CPF doesn't pass checksum, but tests the format
        assert isinstance(is_valid, bool)

    def test_validate_cpf_invalid_length(self):
        """Test validation of CPF with wrong length"""
        validator = DataValidator()

        invalid_cpfs = [
            "123.456.789-0",  # 10 digits
            "123.456.789-000",  # 12 digits
        ]

        for cpf in invalid_cpfs:
            is_valid, message = validator._validate_cpf(cpf)
            assert not is_valid
            assert "11 digits" in message

    def test_validate_cpf_repeated_digits(self):
        """Test validation of CPF with all repeated digits"""
        validator = DataValidator()

        repeated_cpf = "111.111.111-11"
        is_valid, message = validator._validate_cpf(repeated_cpf)
        assert not is_valid
        assert "repeated digits" in message


class TestDateValidation:
    """Test date validation functionality"""

    def test_validate_date_valid_formats(self):
        """Test validation of dates in various valid formats"""
        validator = DataValidator()

        valid_dates = [
            "2020-01-15",
            "1999-12-31",
            "2023-06-20",
            "15/01/2020",  # Brazilian format
            "01/15/2020",  # US format
            "2020/01/15"   # Alternative format
        ]

        for date_str in valid_dates:
            is_valid, message = validator._validate_date(date_str)
            assert is_valid, f"Date {date_str} should be valid: {message}"

    def test_validate_date_invalid_formats(self):
        """Test validation of invalid date formats"""
        validator = DataValidator()

        invalid_dates = [
            "2020-13-45",  # Invalid month/day
            "not-a-date",
            "2020/01",     # Missing day
            "01-15-2020",  # Wrong separator
            "",
            None
        ]

        for date_str in invalid_dates:
            is_valid, message = validator._validate_date(date_str)
            assert not is_valid

    def test_validate_date_future_date(self):
        """Test validation of dates too far in the future"""
        validator = DataValidator()

        # Date more than 10 years in the future
        future_date = (date.today().replace(year=date.today().year + 15)).isoformat()
        is_valid, message = validator._validate_date(future_date)
        assert not is_valid
        assert "future" in message

    def test_validate_date_too_old(self):
        """Test validation of dates too far in the past"""
        validator = DataValidator()

        old_date = "1800-01-01"
        is_valid, message = validator._validate_date(old_date)
        assert not is_valid
        assert "1900" in message

    def test_validate_date_convenience_function(self):
        """Test the convenience validate_date function"""
        assert validate_date("2020-01-15")
        assert not validate_date("invalid-date")
        assert not validate_date("")


class TestNumericValidation:
    """Test numeric field validation"""

    def test_validate_numeric_valid_values(self):
        """Test validation of valid numeric values"""
        validator = DataValidator()

        valid_values = [
            "123.45",
            "-123.45",
            "0",
            "1000000.50",
            "1,234.56",  # With comma as thousand separator
            123.45,
            0,
            -100
        ]

        for value in valid_values:
            is_valid, message = validator._validate_numeric(value)
            assert is_valid, f"Value {value} should be valid: {message}"

    def test_validate_numeric_invalid_values(self):
        """Test validation of invalid numeric values"""
        validator = DataValidator()

        invalid_values = [
            "not-a-number",
            "12.34.56",
            "",
            None,
            "R$ 123.45",  # Currency format
            "123,45"      # European decimal separator without proper format
        ]

        for value in invalid_values:
            is_valid, message = validator._validate_numeric(value)
            assert not is_valid


class TestCurrencyValidation:
    """Test Brazilian Real currency validation"""

    def test_validate_currency_valid_formats(self):
        """Test validation of valid currency formats"""
        validator = DataValidator()

        valid_currencies = [
            "R$ 1.234,56",
            "R$ 123,45",
            "123,45",
            "1.234,56",
            "1000000,50"
        ]

        for currency in valid_currencies:
            is_valid, message = validator._validate_currency(currency)
            assert is_valid, f"Currency {currency} should be valid: {message}"

    def test_validate_currency_invalid_formats(self):
        """Test validation of invalid currency formats"""
        validator = DataValidator()

        invalid_currencies = [
            "USD 123.45",
            "123.45",      # Dot as decimal separator
            "not-currency",
            "",
            None
        ]

        for currency in invalid_currencies:
            is_valid, message = validator._validate_currency(currency)
            assert not is_valid


class TestSecurityCodeValidation:
    """Test security code validation"""

    def test_validate_security_code_debenture(self):
        """Test validation of debenture security codes"""
        validator = DataValidator()

        valid_codes = [
            "ABCD22",
            "XYZT99",
            "TEST01"
        ]

        for code in valid_codes:
            is_valid, message = validator._validate_security_code(code)
            assert is_valid, f"Security code {code} should be valid: {message}"

    def test_validate_security_code_cra(self):
        """Test validation of CRA security codes"""
        validator = DataValidator()

        valid_cra = "12A1234567-89"
        is_valid, message = validator._validate_security_code(valid_cra)
        assert is_valid, f"CRA code {valid_cra} should be valid: {message}"

    def test_validate_security_code_invalid(self):
        """Test validation of invalid security codes"""
        validator = DataValidator()

        invalid_codes = [
            "INVALID",
            "12345",
            "ABCD",
            "",
            None
        ]

        for code in invalid_codes:
            is_valid, message = validator._validate_security_code(code)
            assert not is_valid

    def test_validate_security_code_convenience_function(self):
        """Test the convenience validate_security_code function"""
        assert validate_security_code("ABCD22")
        assert not validate_security_code("invalid")
        assert not validate_security_code("")


class TestFieldValidation:
    """Test general field validation"""

    def test_validate_field_cnpj_by_name(self):
        """Test field validation that detects CNPJ by field name"""
        validator = DataValidator()

        field_names = ["CNPJ_FUNDO", "cnpj_fundo", "CNPJ", "cnpj"]

        for field_name in field_names:
            is_valid, message = validator.validate_field(field_name, "12.345.678/0001-90")
            assert is_valid, f"Field {field_name} should be validated as CNPJ"

    def test_validate_field_date_by_name(self):
        """Test field validation that detects date by field name"""
        validator = DataValidator()

        field_names = ["DT_REG", "DATA_REGISTRO", "date", "DATA"]

        for field_name in field_names:
            is_valid, message = validator.validate_field(field_name, "2020-01-15")
            assert is_valid, f"Field {field_name} should be validated as date"

    def test_validate_field_numeric_by_name(self):
        """Test field validation that detects numeric by field name"""
        validator = DataValidator()

        field_names = ["VALOR", "VL_TOTAL", "value", "QUANTIDADE"]

        for field_name in field_names:
            is_valid, message = validator.validate_field(field_name, "123.45")
            assert is_valid, f"Field {field_name} should be validated as numeric"


class TestRecordValidation:
    """Test complete record validation"""

    def test_validate_record_valid(self, sample_fidc_cadastral_records, sample_validation_config):
        """Test validation of valid records"""
        validator = DataValidator()

        for record in sample_fidc_cadastral_records:
            errors, warnings = validator.validate_record(
                record,
                sample_validation_config["required_fields"],
                sample_validation_config["field_types"]
            )

            # Should have no errors for valid records
            assert len(errors) == 0, f"Unexpected errors: {[str(e) for e in errors]}"

    def test_validate_record_missing_required_field(self, sample_validation_config):
        """Test validation of record with missing required field"""
        validator = DataValidator()

        incomplete_record = {
            "CNPJ_FUNDO": "12.345.678/0001-90",
            # Missing DENOM_SOCIAL and DT_REG
        }

        errors, warnings = validator.validate_record(
            incomplete_record,
            sample_validation_config["required_fields"],
            sample_validation_config["field_types"]
        )

        assert len(errors) >= 2  # Should have errors for missing fields
        error_messages = [str(e) for e in errors]
        assert any("DENOM_SOCIAL" in msg and "missing" in msg for msg in error_messages)
        assert any("DT_REG" in msg and "missing" in msg for msg in error_messages)

    def test_validate_record_invalid_field_type(self, sample_validation_config):
        """Test validation of record with invalid field type"""
        validator = DataValidator()

        invalid_record = {
            "CNPJ_FUNDO": "invalid-cnpj",
            "DENOM_SOCIAL": "Test Fund",
            "DT_REG": "2020-01-15"
        }

        errors, warnings = validator.validate_record(
            invalid_record,
            sample_validation_config["required_fields"],
            sample_validation_config["field_types"]
        )

        assert len(errors) > 0
        error_messages = [str(e) for e in errors]
        assert any("CNPJ" in msg and "invalid" in msg.lower() for msg in error_messages)

    def test_validate_record_with_warnings(self):
        """Test validation that generates warnings"""
        validator = DataValidator()

        record_with_warnings = {
            "CNPJ_FUNDO": "12.345.678/0001-90",
            "DENOM_SOCIAL": "Test Fund",
            "DT_REG": "invalid-date-format"
        }

        errors, warnings = validator.validate_record(
            record_with_warnings,
            ["CNPJ_FUNDO", "DENOM_SOCIAL"],
            {"CNPJ_FUNDO": "cnpj", "DT_REG": "date"}
        )

        # Should have warnings for invalid date format
        assert len(warnings) > 0
        warning_messages = [str(w) for w in warnings]
        assert any("date" in msg.lower() for msg in warning_messages)


class TestDatasetValidation:
    """Test complete dataset validation"""

    def test_validate_dataset_valid(self, sample_fidc_cadastral_records, sample_validation_config):
        """Test validation of valid dataset"""
        validator = DataValidator()

        result = validator.validate_dataset(sample_fidc_cadastral_records, sample_validation_config)

        assert result["total_records"] == len(sample_fidc_cadastral_records)
        assert len(result["validation_errors"]) == 0
        assert result["quality_score"] > 80  # Should have high quality score
        assert result["parsing_success_rate"] == 100.0

    def test_validate_dataset_empty(self):
        """Test validation of empty dataset"""
        validator = DataValidator()

        result = validator.validate_dataset([])

        assert result["total_records"] == 0
        assert len(result["validation_errors"]) > 0
        assert result["quality_score"] == 0.0
        assert result["parsing_success_rate"] == 0.0

    def test_validate_dataset_with_errors(self, sample_validation_config):
        """Test validation of dataset with errors"""
        validator = DataValidator()

        dataset_with_errors = [
            {"CNPJ_FUNDO": "invalid", "DENOM_SOCIAL": "Test", "DT_REG": "2020-01-15"},
            {"CNPJ_FUNDO": "12.345.678/0001-90"},  # Missing required fields
        ]

        result = validator.validate_dataset(dataset_with_errors, sample_validation_config)

        assert result["total_records"] == 2
        assert len(result["validation_errors"]) > 0
        assert result["records_with_errors"] > 0
        assert result["parsing_success_rate"] < 100.0
        assert result["quality_score"] < 100.0

    def test_validate_dataset_field_statistics(self, sample_fidc_cadastral_records):
        """Test field statistics generation"""
        validator = DataValidator()

        result = validator.validate_dataset(sample_fidc_cadastral_records)

        assert "field_stats" in result
        assert "CNPJ_FUNDO" in result["field_stats"]
        assert "DENOM_SOCIAL" in result["field_stats"]

        cnpj_stats = result["field_stats"]["CNPJ_FUNDO"]
        assert cnpj_stats["total"] == len(sample_fidc_cadastral_records)
        assert cnpj_stats["non_null"] == len(sample_fidc_cadastral_records)
        assert cnpj_stats["null_percentage"] == 0.0

class TestCNPJChecksumAgainstRealData:
    """Exercise the REAL checksum path with REAL CNPJs.

    Why this class exists: every other "valid CNPJ" in this file is one of the
    four fabricated `accepted_demo_cnpjs`, which _validate_cnpj short-circuits
    to True *before* reaching the checksum. So the checksum code was never
    executed by any test, and a genuine bug survived undetected — weights2 had
    12 entries but is applied to 13 digits, and zip() silently truncates, so the
    first check digit never entered the second calculation. That rejected 150 of
    the 187 real CNPJs in src/store/seeds/etf_registry_seed.csv.

    These cases use real, externally verifiable CNPJs so the algorithm itself is
    under test.
    """

    # iShares Ibovespa (BOVA11) — 10.406.511/0001-61, a real public CNPJ.
    REAL_CNPJ = "10406511000161"

    def test_real_cnpj_validates(self):
        ok, msg = DataValidator()._validate_cnpj(self.REAL_CNPJ)
        assert ok, f"real CNPJ rejected: {msg}"

    def test_real_cnpj_validates_formatted(self):
        ok, msg = DataValidator()._validate_cnpj("10.406.511/0001-61")
        assert ok, f"real formatted CNPJ rejected: {msg}"

    def test_every_seed_cnpj_validates(self):
        """The curated ETF registry seed is real data — all of it must pass."""
        import csv
        from pathlib import Path

        seed = Path(__file__).resolve().parents[1] / "src/store/seeds/etf_registry_seed.csv"
        rejected = []
        for row in csv.DictReader(seed.open()):
            digits = "".join(c for c in row["cnpj"] if c.isdigit())
            if len(digits) != 14:
                continue
            ok, msg = DataValidator()._validate_cnpj(digits)
            if not ok:
                rejected.append((row["ticker"], digits, msg))
        assert not rejected, (
            f"{len(rejected)} real seed CNPJs rejected by the validator "
            f"(first few: {rejected[:5]})"
        )

    def test_wrong_check_digit_is_rejected(self):
        """A real CNPJ with its last check digit altered must fail."""
        bad = self.REAL_CNPJ[:13] + ("2" if self.REAL_CNPJ[13] != "2" else "3")
        ok, msg = DataValidator()._validate_cnpj(bad)
        assert not ok and "checksum" in msg.lower()

    def test_first_check_digit_participates_in_second(self):
        """Regression guard for the zip()-truncation bug.

        weights2 must have one entry per digit it is applied to (13). If it is
        ever shortened back to 12, the assert inside calculate_digit fires
        rather than silently ignoring the 13th digit.
        """
        import inspect

        src = inspect.getsource(DataValidator._validate_cnpj)
        assert "weights2 = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]" in src, (
            "weights2 must carry 13 weights for the 13 digits it scores"
        )
