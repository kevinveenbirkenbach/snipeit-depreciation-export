#!/usr/bin/env python3

import os
import sys
import argparse
import requests
import csv
import json
from datetime import datetime, timedelta
from dateutil import parser as dateparser
from dateutil.relativedelta import relativedelta
import re

# Global debug flag
DEBUG = False
# HTTP request timeout in seconds
REQUEST_TIMEOUT = 30

def debug(msg):
    """
    Print debug messages if DEBUG is True.
    """
    if DEBUG:
        print(f"[DEBUG] {msg}")

# Resolve the real path of the script so it works correctly via symlinks
script_path = os.path.realpath(__file__)
script_dir  = os.path.dirname(script_path)
os.chdir(script_dir)

def fetch_all_assets(api_token, base_url):
    """
    Fetch all hardware assets from Snipe-IT using the paginated list endpoint.
    Returns a list of asset summaries (each with fields like 'id' and 'asset_tag').
    """
    debug("Starting to fetch assets (list endpoint) from Snipe-IT")
    assets = []
    page   = 1
    per_page = 100
    headers = {
        'Authorization': f'Bearer {api_token}',
        'Accept': 'application/json'
    }

    while True:
        debug(f"  → Requesting page {page} (limit={per_page})")
        url    = f"{base_url.rstrip('/')}/api/v1/hardware"
        params = {'limit': per_page, 'page': page}
        try:
            response = requests.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
        except requests.Timeout:
            print(f"[ERROR] Request timed out after {REQUEST_TIMEOUT} seconds on page {page}")
            sys.exit(1)
        except requests.RequestException as e:
            print(f"[ERROR] Failed to fetch assets on page {page}: {e}")
            sys.exit(1)

        data = response.json()
        rows = data.get('rows', [])
        assets.extend(rows)

        total_pages = data.get('total_pages', 0)
        debug(f"    → Received {len(rows)} rows on page {page} (total_pages={total_pages})")

        if page >= total_pages:
            break
        page += 1

    debug(f"Finished fetching assets (list endpoint). Total assets fetched: {len(assets)}")
    return assets

def fetch_asset_detail(asset_id, api_token, base_url):
    """
    Fetch the full details of a single asset from Snipe-IT:
    GET /api/v1/hardware/{asset_id}
    This endpoint returns fields such as purchase_date, purchase_cost, and depreciation (id + name).
    """
    debug(f"    → Fetching detail for Asset ID = {asset_id}")
    headers = {
        'Authorization': f'Bearer {api_token}',
        'Accept': 'application/json'
    }
    url = f"{base_url.rstrip('/')}/api/v1/hardware/{asset_id}"
    try:
        response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
    except requests.Timeout:
        print(f"[ERROR] Detail request timed out after {REQUEST_TIMEOUT} seconds for Asset {asset_id}")
        sys.exit(1)
    except requests.RequestException as e:
        print(f"[ERROR] Failed to fetch details for Asset {asset_id}: {e}")
        sys.exit(1)

    detail = response.json()
    if DEBUG:
        print(f"[DEBUG] Full detail response for Asset ID {asset_id}:\n{json.dumps(detail, indent=4)}")
    return detail

def fetch_model_detail(model_id, api_token, base_url):
    """
    Fetch the full details of a single model from Snipe-IT:
    GET /api/v1/models/{model_id}
    This endpoint returns fields such as depreciation (id + name).
    """
    debug(f"      → Fetching detail for Model ID = {model_id}")
    headers = {
        'Authorization': f'Bearer {api_token}',
        'Accept': 'application/json'
    }
    url = f"{base_url.rstrip('/')}/api/v1/models/{model_id}"
    try:
        response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
    except requests.Timeout:
        print(f"[ERROR] Model detail request timed out after {REQUEST_TIMEOUT} seconds for Model {model_id}")
        sys.exit(1)
    except requests.RequestException as e:
        print(f"[ERROR] Failed to fetch model details for Model {model_id}: {e}")
        sys.exit(1)

    model_detail = response.json()
    if DEBUG:
        print(f"[DEBUG] Full detail response for Model ID {model_id}:\n{json.dumps(model_detail, indent=4)}")
    return model_detail

def fetch_depreciation_schedule(schedule_id, api_token, base_url):
    """
    Fetch the depreciation schedule (contains actual month count) from:
    GET /api/v1/depreciations/{schedule_id}
    """
    debug(f"        → Fetching depreciation schedule ID = {schedule_id}")
    headers = {
        'Authorization': f'Bearer {api_token}',
        'Accept': 'application/json'
    }
    url = f"{base_url.rstrip('/')}/api/v1/depreciations/{schedule_id}"
    try:
        response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
    except requests.Timeout:
        print(f"[ERROR] Depreciation schedule request timed out after {REQUEST_TIMEOUT} seconds for Schedule {schedule_id}")
        sys.exit(1)
    except requests.RequestException as e:
        print(f"[ERROR] Failed to fetch depreciation schedule {schedule_id}: {e}")
        sys.exit(1)

    schedule_detail = response.json()
    if DEBUG:
        print(f"[DEBUG] Full detail response for Depreciation Schedule ID {schedule_id}:\n{json.dumps(schedule_detail, indent=4)}")
    return schedule_detail

def parse_months_field(months_str):
    """
    Extract integer month count from a string such as "36 months" or "36 Month".
    Returns the integer or raises ValueError.
    """
    match = re.search(r'(\d+)', months_str)
    if not match:
        raise ValueError(f"Cannot extract integer from '{months_str}'")
    return int(match.group(1))

def compute_depreciation_from_detail(detail_obj, api_token, base_url, start_date, end_date):
    """
    Compute depreciation (daily straight-line) for a single asset based on its detailed data.
    Expects detail_obj to contain:
      - detail_obj["purchase_date"]["date"]         (e.g., "2022-08-01")
      - detail_obj["purchase_cost"]                  (e.g., "4,049.58")
      - detail_obj["depreciation"]["id"]             (e.g., 1) as a reference to a Depreciation schedule,
           where the schedule has a "months" field like "36 months"
    Returns the depreciation amount (float) for the period [start_date .. end_date],
    or 0.0 if no depreciation applies in that range.
    """
    asset_id = detail_obj.get('id')
    asset_tag = detail_obj.get('asset_tag') or detail_obj.get('name') or 'Unknown'
    debug(f"      Computing depreciation for Asset '{asset_tag}' (ID={asset_id})")

    # 1) Extract and parse purchase_date
    pd_field = detail_obj.get('purchase_date')
    if not pd_field or pd_field.get('date') is None:
        debug(f"        No purchase_date available for '{asset_tag}'")
        return 0.0
    purchase_date_str = pd_field.get('date')
    debug(f"        Raw purchase_date_str = {purchase_date_str}")
    try:
        purchase_date = dateparser.parse(purchase_date_str).date()
        debug(f"        Parsed purchase_date = {purchase_date}")
    except Exception as e:
        debug(f"        Failed to parse purchase_date '{purchase_date_str}' for '{asset_tag}': {e}")
        return 0.0

    # 2) Extract purchase_cost
    raw_cost = detail_obj.get('purchase_cost')
    if not raw_cost:
        debug(f"        No purchase_cost available for '{asset_tag}'")
        return 0.0
    debug(f"        Raw purchase_cost = {raw_cost}")
    cost_str = raw_cost.replace(',', '')
    try:
        cost = float(cost_str)
        debug(f"        Parsed cost = {cost}")
    except ValueError as e:
        debug(f"        Failed to parse cost '{cost_str}' for '{asset_tag}': {e}")
        return 0.0

    # 3) Determine depreciation months:
    depr_obj = detail_obj.get('depreciation')
    if depr_obj and depr_obj.get('id') is not None:
        schedule_id = depr_obj.get('id')
        debug(f"        Found asset.depreciation.id = {schedule_id}")
        schedule_detail = fetch_depreciation_schedule(schedule_id, api_token, base_url)
        months_field = schedule_detail.get('months')
        if not months_field:
            debug(f"        Depreciation schedule {schedule_id} contains no 'months'")
            return 0.0
        debug(f"        Raw schedule.months = {months_field}")
        try:
            life_months = parse_months_field(months_field)
            debug(f"        Parsed schedule.months = {life_months}")
        except ValueError as e:
            debug(f"        Failed to parse schedule.months '{months_field}' for '{asset_tag}': {e}")
            return 0.0
    else:
        # Fallback: If asset has no own depreciation, use model's depreciation
        model_info = detail_obj.get('model', {})
        model_id = model_info.get('id')
        if model_id is None:
            debug(f"        No model ID for '{asset_tag}', cannot determine depreciation")
            return 0.0
        model_detail = fetch_model_detail(model_id, api_token, base_url)
        model_depr_obj = model_detail.get('depreciation')
        if not model_depr_obj or model_depr_obj.get('id') is None:
            debug(f"        Model ID {model_id} has no depreciation info for '{asset_tag}'")
            return 0.0
        schedule_id = model_depr_obj.get('id')
        debug(f"        Found model.depreciation.id = {schedule_id}")
        schedule_detail = fetch_depreciation_schedule(schedule_id, api_token, base_url)
        months_field = schedule_detail.get('months')
        if not months_field:
            debug(f"        Depreciation schedule {schedule_id} contains no 'months'")
            return 0.0
        debug(f"        Raw schedule.months = {months_field}")
        try:
            life_months = parse_months_field(months_field)
            debug(f"        Parsed schedule.months = {life_months}")
        except ValueError as e:
            debug(f"        Failed to parse schedule.months '{months_field}' for '{asset_tag}': {e}")
            return 0.0

    # 4) Calculate end of useful life (inclusive)
    end_of_life = purchase_date + relativedelta(months=life_months) - timedelta(days=1)
    debug(f"        Calculated end_of_life = {end_of_life}")

    # 5) If fully depreciated before the start_date, skip
    if end_of_life < start_date:
        debug(f"        Asset '{asset_tag}' fully depreciated before {start_date} (end_of_life = {end_of_life}) -> skipping")
        return 0.0

    # 6) Determine the overlapping depreciation period within [start_date .. end_date]
    period_start = max(purchase_date, start_date)
    period_end   = min(end_of_life, end_date)
    debug(f"        Overlap period = ({period_start} .. {period_end})")
    if period_end < period_start:
        debug(f"        No overlap with given range for '{asset_tag}' -> skipping")
        return 0.0

    # 7) Compute total days of useful life
    total_life_days = (end_of_life - purchase_date).days + 1
    daily_depr = cost / total_life_days
    debug(f"        Total life days = {total_life_days}, daily_depr = {daily_depr:.6f}")

    # 8) Count days in the depreciation window
    depr_days = (period_end - period_start).days + 1
    depr_amount = round(daily_depr * depr_days, 2)
    debug(f"        Depreciation days = {depr_days}, depr_amount = {depr_amount:.2f}")

    return depr_amount

def generate_qif(depr_entries, expense_account, contra_account, qif_filename, qif_date):
    """
    Generate a QIF file with split transactions for depreciation entries.
    Each entry will debit 'expense_account' and credit 'contra_account'.
    """
    debug(f"Generating QIF file at '{qif_filename}'")
    try:
        with open(qif_filename, 'w', newline='') as qif_file:
            # QIF header for Bank type (for split transactions)
            qif_file.write("!Type:Bank\n")
            for entry in depr_entries:
                amount    = entry['depreciation']
                asset_tag = entry['asset_tag']
                date_str  = qif_date.strftime('%m/%d/%Y')

                # Entire transaction amount is 0.00; splits offset each other
                qif_file.write(f"D{date_str}\n")
                qif_file.write("T0.00\n")
                qif_file.write(f"PDepreciation: {asset_tag}\n")
                # First split: depreciation expense (positive)
                qif_file.write(f"S{expense_account}\n")
                qif_file.write(f"${amount:.2f}\n")
                # Second split: accumulated depreciation (negative)
                qif_file.write(f"S{contra_account}\n")
                qif_file.write(f"$-{amount:.2f}\n")
                qif_file.write("^\n")
    except OSError as e:
        print(f"[ERROR] Failed to write QIF file: {e}")
        sys.exit(1)
    debug(f"QIF file generation completed: '{qif_filename}'")

def main():
    parser = argparse.ArgumentParser(
        description="Fetch assets from Snipe-IT, compute depreciation (AfA) for a given period, "
                    "and optionally generate a QIF file for booking."
    )
    parser.add_argument('--api-token', required=True,
                        help='Snipe-IT API token')
    parser.add_argument('--base-url', required=True,
                        help='Base URL of your Snipe-IT instance (e.g., https://inventory.veen.world)')
    parser.add_argument('--start-date', required=True,
                        help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', required=True,
                        help='End date (YYYY-MM-DD)')
    parser.add_argument('--expense-account', required=True,
                        help='Account name for depreciation expense (e.g., Expenses:Depreciation)')
    parser.add_argument('--contra-account', required=True,
                        help='Account name for accumulated depreciation (e.g., Assets:AccumulatedDepreciation)')
    parser.add_argument('--qif', action='store_true',
                        help='If set, generate a QIF file with depreciation bookings')
    parser.add_argument('--qif-output', default='depreciation.qif',
                        help='Filename for QIF output (if --qif is set)')
    parser.add_argument('--debug', action='store_true',
                        help='Enable debug output')

    args = parser.parse_args()
    global DEBUG
    DEBUG = args.debug

    debug("Script started")
    debug(f"Resolved script directory to '{script_dir}'")

    # Parse input dates
    try:
        start_date = datetime.strptime(args.start_date, '%Y-%m-%d').date()
        end_date   = datetime.strptime(args.end_date,   '%Y-%m-%d').date()
        debug(f"Parsed start_date={start_date}, end_date={end_date}")
    except ValueError as e:
        print(f"[ERROR] Failed to parse dates: {e}")
        sys.exit(1)

    # 1) Fetch asset summaries via list endpoint
    assets = fetch_all_assets(args.api_token, args.base_url)

    # 2) For each asset summary, fetch full details to get purchase_date, purchase_cost, depreciation schedule
    depreciation_entries = []
    total_depreciation   = 0.0
    debug("Starting depreciation calculations for each asset (detail endpoint)")

    for asset_summary in assets:
        asset_id  = asset_summary.get('id')
        asset_tag = asset_summary.get('asset_tag') or asset_summary.get('name') or 'Unknown'
        if asset_id is None:
            debug(f"  → Skipping asset without ID (tag={asset_tag})")
            continue

        detail = fetch_asset_detail(asset_id, args.api_token, args.base_url)

        depr_amount = compute_depreciation_from_detail(detail, args.api_token, args.base_url, start_date, end_date)
        debug(f"    → Computed depreciation for '{asset_tag}' = {depr_amount:.2f}")
        if depr_amount > 0:
            total_depreciation += depr_amount
            depreciation_entries.append({
                'asset_tag': asset_tag,
                'depreciation': depr_amount
            })

    debug(f"Depreciation calculation completed. Assets with depreciation > 0: {len(depreciation_entries)}")
    debug(f"Total depreciation: {total_depreciation:.2f} EUR")

    # 3) Write summary CSV
    csv_path = os.path.join(script_dir, 'depreciation_summary.csv')
    debug(f"Writing depreciation summary to CSV at '{csv_path}'")
    try:
        with open(csv_path, 'w', newline='') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(['Asset Tag', 'Depreciation Amount'])
            for entry in depreciation_entries:
                writer.writerow([entry['asset_tag'], f"{entry['depreciation']:.2f}"])
    except OSError as e:
        print(f"[ERROR] Failed to write CSV file: {e}")
        sys.exit(1)

    print(f"Depreciation summary written to '{csv_path}'. Total depreciation: {total_depreciation:.2f} EUR")

    # 4) If requested, generate QIF file
    if args.qif:
        qif_path = os.path.join(script_dir, args.qif_output)
        generate_qif(
            depreciation_entries,
            args.expense_account,
            args.contra_account,
            qif_path,
            end_date
        )
        print(f"QIF file generated: '{qif_path}'")

    debug("Script finished")

if __name__ == '__main__':
    main()
