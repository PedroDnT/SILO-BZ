"""
Tests for CSV parsing functions in CVM data service
Tests various CSV formats, encodings, and error conditions
"""

import pytest
import io
import zipfile
from unittest.mock import patch, Mock

from src.cvm_api.services import CVMCreditDataService


class TestCSVParseContent:
    """Test CSV content parsing functionality"""

    def test_parse_valid_csv_latin1_semicolon(self, sample_cvm_csv_data):
        """Test parsing valid CSV with latin-1 encoding and semicolon separator"""
        service = CVMCreditDataService()

        result = service._parse_csv_content(sample_cvm_csv_data)

        assert len(result) == 3
        assert result[0]["CNPJ_FUNDO"] == "12.345.678/0001-90"
        assert result[0]["DENOM_SOCIAL"] == "FUNDO EXEMPLO FIDC"
        assert result[0]["DT_REG"] == "2020-01-15"
        assert result[0]["SIT"] == "ATIVO"

    def test_parse_csv_with_whitespace(self):
        """Test parsing CSV with extra whitespace"""
        csv_data = """CNPJ_FUNDO ; DENOM_SOCIAL ; DT_REG
  12.345.678/0001-90  ;  FUNDO EXEMPLO  ;  2020-01-15
98.765.432/0001-10; FUNDO TESTE ;2019-06-20
"""
        service = CVMCreditDataService()

        result = service._parse_csv_content(csv_data)

        assert len(result) == 2
        assert result[0]["CNPJ_FUNDO"] == "12.345.678/0001-90"
        assert result[0]["DENOM_SOCIAL"] == "FUNDO EXEMPLO"
        assert result[1]["CNPJ_FUNDO"] == "98.765.432/0001-10"

    def test_parse_empty_csv(self, sample_empty_csv):
        """Test parsing empty CSV file"""
        service = CVMCreditDataService()

        with pytest.raises(ValueError, match="No data records found"):
            service._parse_csv_content(sample_empty_csv)

    def test_parse_csv_with_only_headers(self):
        """Test parsing CSV with only headers and no data"""
        csv_data = "CNPJ_FUNDO;DENOM_SOCIAL;DT_REG\n"
        service = CVMCreditDataService()

        with pytest.raises(ValueError, match="No data records found"):
            service._parse_csv_content(csv_data)

    def test_parse_malformed_csv(self, sample_malformed_csv):
        """Test parsing malformed CSV (comma instead of semicolon)"""
        service = CVMCreditDataService()

        # Should still parse but may have issues with quoted fields
        result = service._parse_csv_content(sample_malformed_csv)
        assert len(result) >= 1  # At least some data should be parsed

    def test_parse_csv_with_null_values(self):
        """Test parsing CSV with NULL/empty values"""
        csv_data = """CNPJ_FUNDO;DENOM_SOCIAL;DT_REG;DT_CANCEL
12.345.678/0001-90;FUNDO EXEMPLO;2020-01-15;
98.765.432/0001-10;FUNDO TESTE;;2023-12-31
;;2021-03-10;2022-05-20
"""
        service = CVMCreditDataService()

        result = service._parse_csv_content(csv_data)

        assert len(result) == 3
        assert result[0]["DT_CANCEL"] is None or result[0]["DT_CANCEL"] == ""
        assert result[1]["DT_REG"] is None or result[1]["DT_REG"] == ""
        assert result[2]["CNPJ_FUNDO"] is None or result[2]["CNPJ_FUNDO"] == ""

    def test_parse_csv_different_encodings(self):
        """Test parsing CSV with different encodings"""
        # UTF-8 encoded CSV
        utf8_csv = """CNPJ_FUNDO;DENOM_SOCIAL;DT_REG
12.345.678/0001-90;FUNDO TÉSTE UTF-8;2020-01-15
""".encode('utf-8').decode('utf-8')

        service = CVMCreditDataService()

        result = service._parse_csv_content(utf8_csv)
        assert len(result) == 1
        assert "UTF-8" in result[0]["DENOM_SOCIAL"] or "TÉSTE" in result[0]["DENOM_SOCIAL"]

    def test_parse_csv_large_dataset(self):
        """Test parsing large CSV dataset"""
        # Generate large CSV data
        rows = []
        for i in range(1000):
            cnpj = f"{i:02d}.{i+10:03d}.{i+20:03d}/0001-{i%100:02d}"
            rows.append(f"{cnpj};FUNDO TESTE {i};2020-01-15")

        large_csv = "CNPJ_FUNDO;DENOM_SOCIAL;DT_REG\n" + "\n".join(rows)

        service = CVMCreditDataService()

        result = service._parse_csv_content(large_csv)

        assert len(result) == 1000
        assert result[0]["CNPJ_FUNDO"] == "00.010.020/0001-00"
        assert result[-1]["CNPJ_FUNDO"] == "999.1009.1019/0001-99"


class TestZIPExtraction:
    """Test ZIP file extraction functionality"""

    def test_extract_csv_from_zip_valid(self, mock_zip_content):
        """Test extracting CSV from valid ZIP file"""
        service = CVMCreditDataService()

        result = service._extract_csv_from_zip(mock_zip_content, "test_data.csv", 2023, 12)

        assert "CNPJ_FUNDO;DENOM_SOCIAL;DT_REG" in result
        assert "12.345.678/0001-90;FUNDO EXEMPLO;2020-01-15" in result
        assert "98.765.432/0001-10;FUNDO TESTE;2019-06-20" in result

    def test_extract_csv_from_zip_no_csv(self):
        """Test extracting from ZIP with no CSV files"""
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zip_file:
            zip_file.writestr("readme.txt", "This is a test file")

        zip_content = zip_buffer.getvalue()
        service = CVMCreditDataService()

        with pytest.raises(ValueError, match="No CSV file found"):
            service._extract_csv_from_zip(zip_content, "data.csv", 2023, 12)

    def test_extract_csv_from_zip_wrong_filename(self, mock_zip_content):
        """Test extracting CSV with wrong filename pattern"""
        service = CVMCreditDataService()

        # Should find the CSV anyway if it's the only one
        result = service._extract_csv_from_zip(mock_zip_content, "nonexistent.csv", 2023, 12)
        assert "CNPJ_FUNDO" in result

    def test_extract_csv_from_invalid_zip(self):
        """Test extracting from invalid ZIP file"""
        invalid_zip = b"This is not a ZIP file"

        service = CVMCreditDataService()

        with pytest.raises(ValueError):
            service._extract_csv_from_zip(invalid_zip, "data.csv", 2023, 12)

    def test_extract_csv_from_zip_multiple_csvs(self):
        """Test extracting from ZIP with multiple CSV files"""
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zip_file:
            zip_file.writestr("data1.csv", "CNPJ;NAME\n123;Test1")
            zip_file.writestr("data2.csv", "CNPJ;NAME\n456;Test2")
            zip_file.writestr("info.txt", "Info file")

        zip_content = zip_buffer.getvalue()
        service = CVMCreditDataService()

        # Should extract first CSV found
        result = service._extract_csv_from_zip(zip_content, "data1.csv", 2023, 12)
        assert "123;Test1" in result


class TestDataValidation:
    """Test data validation after parsing"""

    def test_validate_parsed_data_valid(self, sample_fidc_cadastral_records):
        """Test validation of valid parsed data"""
        service = CVMCreditDataService()

        # Should not raise exception
        service._validate_parsed_data(sample_fidc_cadastral_records)

    def test_validate_parsed_data_empty(self):
        """Test validation of empty data"""
        service = CVMCreditDataService()

        with pytest.raises(ValueError, match="No data records found"):
            service._validate_parsed_data([])

    def test_validate_parsed_data_empty_records(self):
        """Test validation of data with empty records"""
        data = [
            {},
            {"CNPJ_FUNDO": None, "DENOM_SOCIAL": ""},
            {"CNPJ_FUNDO": "123", "DENOM_SOCIAL": None}
        ]

        service = CVMCreditDataService()

        # Should not raise exception but may log warnings
        service._validate_parsed_data(data)

    def test_validate_parsed_data_minimal_valid(self):
        """Test validation of minimal valid data"""
        data = [
            {"CNPJ_FUNDO": "12.345.678/0001-90", "DENOM_SOCIAL": "Test Fund"}
        ]

        service = CVMCreditDataService()

        service._validate_parsed_data(data)


class TestPagination:
    """Test data pagination functionality"""

    def test_paginate_data_first_page(self, sample_fidc_cadastral_records):
        """Test pagination - first page"""
        service = CVMCreditDataService()

        page_data, pagination_info = service._paginate_data(sample_fidc_cadastral_records, 1, 10)

        assert len(page_data) == 2
        assert pagination_info.page == 1
        assert pagination_info.page_size == 10
        assert pagination_info.total_items == 2
        assert pagination_info.total_pages == 1
        assert not pagination_info.has_next
        assert not pagination_info.has_previous

    def test_paginate_data_second_page(self):
        """Test pagination - second page"""
        data = [{"id": i, "value": f"test_{i}"} for i in range(25)]
        service = CVMCreditDataService()

        page_data, pagination_info = service._paginate_data(data, 2, 10)

        assert len(page_data) == 10
        assert pagination_info.page == 2
        assert pagination_info.total_items == 25
        assert pagination_info.total_pages == 3
        assert pagination_info.has_next
        assert pagination_info.has_previous
        assert page_data[0]["id"] == 10
        assert page_data[-1]["id"] == 19

    def test_paginate_data_empty(self):
        """Test pagination with empty data"""
        service = CVMCreditDataService()

        page_data, pagination_info = service._paginate_data([], 1, 10)

        assert len(page_data) == 0
        assert pagination_info.total_items == 0
        assert pagination_info.total_pages == 0
        assert not pagination_info.has_next
        assert not pagination_info.has_previous

    def test_paginate_data_page_beyond_bounds(self):
        """Test pagination with page number beyond available data"""
        data = [{"id": i} for i in range(5)]
        service = CVMCreditDataService()

        page_data, pagination_info = service._paginate_data(data, 10, 10)

        assert len(page_data) == 0
        assert pagination_info.page == 10
        assert pagination_info.total_items == 5
        assert pagination_info.total_pages == 1
        assert not pagination_info.has_next
        assert pagination_info.has_previous

    def test_paginate_data_large_page_size(self, sample_fidc_cadastral_records):
        """Test pagination with page size larger than data"""
        service = CVMCreditDataService()

        page_data, pagination_info = service._paginate_data(sample_fidc_cadastral_records, 1, 100)

        assert len(page_data) == 2
        assert pagination_info.total_pages == 1
        assert not pagination_info.has_next