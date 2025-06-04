import argparse
import requests
import csv
from datetime import datetime, timedelta
from dateutil import parser as dateparser
from dateutil.relativedelta import relativedelta

def fetch_all_assets(api_token, base_url):
    """
    Fetch all assets from Snipe-IT via paginated API.
    """
    assets = []
    page = 1
    per_page = 100
    headers = {
        'Authorization': f'Bearer {api_token}',
        'Accept': 'application/json'
    }
    
    while True:
        url = f"{base_url.rstrip('/')}/api/v1/hardware"
        params = {'limit': per_page, 'page': page}
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        data = response.json()
        
        assets.extend(data.get('rows', []))
        if page >= data.get('total_pages', 0):
            break
        page += 1
        
    return assets

def compute_depreciation(asset, start_date, end_date):
    """
    Compute depreciation for a single asset between start_date and end_date.
    Assumes asset has 'purchase_date', 'purchase_price', and 'depreciation_months'.
    Returns depreciation amount (float), or 0 if no depreciation in period.
    """
    purchase_date_str = asset.get('purchase_date')
    purchase_price = asset.get('purchase_price')
    depreciation_months = asset.get('depreciation_months')
    
    if not purchase_date_str or not purchase_price or not depreciation_months:
        return 0.0
    
    try:
        purchase_date = dateparser.parse(purchase_date_str).date()
        cost = float(purchase_price)
        life_months = int(depreciation_months)
    except Exception:
        return 0.0
    
    # Calculate end of useful life
    end_of_life = purchase_date + relativedelta(months=life_months) - timedelta(days=1)
    
    # If asset fully depreciated before start_date, nothing to do
    if end_of_life < start_date:
        return 0.0
    
    # Depreciation period for this asset
    period_start = max(purchase_date, start_date)
    period_end = min(end_of_life, end_date)
    
    if period_end < period_start:
        return 0.0
    
    days_in_year = 365.0
    total_life_days = (end_of_life - purchase_date).days + 1
    daily_depr = cost / total_life_days
    
    depr_days = (period_end - period_start).days + 1
    depr_amount = round(daily_depr * depr_days, 2)
    
    return depr_amount

def generate_qif(depr_entries, expense_account, contra_account, qif_filename, qif_date):
    """
    Generate a QIF file with split transactions for depreciation entries.
    Each entry will debit expense_account and credit contra_account.
    """
    with open(qif_filename, 'w', newline='') as qif_file:
        # QIF header for Bank type (useful for split transactions)
        qif_file.write("!Type:Bank\n")
        
        for entry in depr_entries:
            amount = entry['depreciation']
            asset_tag = entry['asset_tag']
            date_str = qif_date.strftime('%m/%d/%Y')
            
            # Total transaction amount is zero (offsetting splits)
            qif_file.write(f"D{date_str}\n")
            qif_file.write("T0.00\n")
            qif_file.write(f"PDepreciation: {asset_tag}\n")
            # First split: depreciation expense (positive amount)
            qif_file.write(f"S{expense_account}\n")
            qif_file.write(f"E{amount:.2f}\n")
            # Second split: accumulated depreciation (negative amount)
            qif_file.write(f"S{contra_account}\n")
            qif_file.write(f"E-{amount:.2f}\n")
            qif_file.write("^\n")

def main():
    parser = argparse.ArgumentParser(
        description="Fetch assets from Snipe-IT, compute depreciation (AfA) for a given period, "
                    "and optionally generate a QIF file for booking."
    )
    parser.add_argument('--api-token', required=True, help='Snipe-IT API token')
    parser.add_argument('--base-url', required=True, help='Base URL of your Snipe-IT instance (e.g., https://snipeit.example.com)')
    parser.add_argument('--start-date', required=True, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', required=True, help='End date (YYYY-MM-DD)')
    parser.add_argument('--expense-account', required=True, help='Account name for depreciation expense (e.g., Expenses:Depreciation)')
    parser.add_argument('--contra-account', required=True, help='Account name for accumulated depreciation (e.g., Assets:AccumulatedDepreciation)')
    parser.add_argument('--qif', action='store_true', help='If set, generate a QIF file with depreciation bookings')
    parser.add_argument('--qif-output', default='depreciation.qif', help='Filename for QIF output (if --qif is set)')
    
    args = parser.parse_args()
    
    # Parse dates
    start_date = datetime.strptime(args.start_date, '%Y-%m-%d').date()
    end_date = datetime.strptime(args.end_date, '%Y-%m-%d').date()
    
    # Fetch assets
    assets = fetch_all_assets(args.api_token, args.base_url)
    
    # Compute depreciation for each asset
    depreciation_entries = []
    total_depreciation = 0.0
    
    for asset in assets:
        depr = compute_depreciation(asset, start_date, end_date)
        if depr > 0:
            total_depreciation += depr
            depreciation_entries.append({
                'asset_tag': asset.get('name', 'Unknown'),
                'depreciation': depr
            })
    
    # Output summary CSV to a file
    with open('depreciation_summary.csv', 'w', newline='') as csvfile:
        csv_writer = csv.writer(csvfile)
        csv_writer.writerow(['Asset Name', 'Depreciation Amount'])
        for entry in depreciation_entries:
            csv_writer.writerow([entry['asset_tag'], f"{entry['depreciation']:.2f}"])
    
    print(f"Depreciation summary written to 'depreciation_summary.csv'. Total depreciation: {total_depreciation:.2f} EUR")
    
    # Generate QIF if requested
    if args.qif:
        generate_qif(
            depreciation_entries,
            args.expense_account,
            args.contra_account,
            args.qif_output,
            end_date
        )
        print(f"QIF file generated: '{args.qif_output}'")

if __name__ == '__main__':
    main()
