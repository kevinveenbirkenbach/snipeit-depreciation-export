import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from datetime import date
import json

# Adjust the import below if your script’s filename is different or if it’s in a package.
import main


class TestMainFunctions(unittest.TestCase):

    def test_parse_months_field_valid(self):
        self.assertEqual(main.parse_months_field("36 months"), 36)
        self.assertEqual(main.parse_months_field("48 Month"), 48)
        self.assertEqual(main.parse_months_field("12"), 12)

    def test_parse_months_field_invalid(self):
        with self.assertRaises(ValueError):
            main.parse_months_field("months")
        with self.assertRaises(ValueError):
            main.parse_months_field("")

    @patch('main.fetch_depreciation_schedule')
    def test_compute_depreciation_from_detail_asset_depr(self, mock_fetch_schedule):
        # Asset detail with a direct depreciation ID
        detail = {
            "id": 1,
            "asset_tag": "Test Asset",
            "purchase_date": {"date": "2020-01-01"},
            "purchase_cost": "1200.00",
            "depreciation": {"id": 999}
        }
        # Depreciation schedule returns "36 months"
        mock_fetch_schedule.return_value = {"months": "36 months"}

        start_date = date(2020, 1, 1)
        end_date = date(2020, 12, 31)
        depr_amount = main.compute_depreciation_from_detail(
            detail, api_token="dummy", base_url="dummy", start_date=start_date, end_date=end_date
        )

        # Life = 36 months → ends 2022-12-31; total life days:
        total_life_days = (date(2022, 12, 31) - date(2020, 1, 1)).days + 1
        # Depreciation days in 2020 = 366 (leap year)
        expected_amount = round((1200.00 / total_life_days) * 366, 2)
        self.assertAlmostEqual(depr_amount, expected_amount)

    @patch('main.fetch_depreciation_schedule')
    @patch('main.fetch_model_detail')
    def test_compute_depreciation_from_detail_model_depr(self, mock_fetch_model, mock_fetch_schedule):
        # Asset detail has no direct depreciation; model provides it
        detail = {
            "id": 2,
            "asset_tag": "Model Asset",
            "purchase_date": {"date": "2021-06-01"},
            "purchase_cost": "3650.00",
            "depreciation": None,
            "model": {"id": 42}
        }
        # Model detail returns depreciation id=100
        mock_fetch_model.return_value = {"depreciation": {"id": 100}}
        # Depreciation schedule returns "36 months"
        mock_fetch_schedule.return_value = {"months": "36 months"}

        start_date = date(2021, 6, 1)
        end_date = date(2021, 12, 31)
        depr_amount = main.compute_depreciation_from_detail(
            detail, api_token="dummy", base_url="dummy", start_date=start_date, end_date=end_date
        )

        # Life = 36 months → ends 2024-05-31
        total_life_days = (date(2024, 5, 31) - date(2021, 6, 1)).days + 1
        # Depreciation days in 2021 from 2021-06-01 to 2021-12-31 = 214
        depr_days = (end_date - start_date).days + 1
        expected_amount = round((3650.00 / total_life_days) * depr_days, 2)
        self.assertAlmostEqual(depr_amount, expected_amount)

    def test_generate_qif(self):
        entries = [
            {"asset_tag": "Asset1", "depreciation": 100.00},
            {"asset_tag": "Asset2", "depreciation": 250.50}
        ]
        expense_account = "4820"
        contra_account = "0409"

        # Use a temporary file to write QIF
        with tempfile.NamedTemporaryFile('r+', delete=False) as tmp:
            qif_path = tmp.name

        qif_date = date(2021, 12, 31)
        main.generate_qif(entries, expense_account, contra_account, qif_path, qif_date)

        # Read back and verify contents
        with open(qif_path, 'r') as f:
            lines = [line.strip() for line in f.readlines() if line.strip()]

        # Basic structure checks
        self.assertEqual(lines[0], "!Type:Bank")

        # First asset's split
        self.assertIn("D12/31/2021", lines)
        self.assertIn("PDepreciation: Asset1", lines)
        self.assertIn("S4820", lines)
        self.assertIn("$100.00", lines)
        self.assertIn("S0409", lines)
        self.assertIn("$-100.00", lines)

        # Second asset's split
        self.assertIn("PDepreciation: Asset2", lines)
        self.assertIn("S4820", lines)
        self.assertIn("$250.50", lines)
        self.assertIn("S0409", lines)
        self.assertIn("$-250.50", lines)


if __name__ == '__main__':
    unittest.main()
