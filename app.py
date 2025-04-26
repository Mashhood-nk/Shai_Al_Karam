import os
import pandas as pd
import matplotlib.pyplot as plt
from flask import Flask, render_template, request, redirect, url_for, send_from_directory
from werkzeug.utils import secure_filename

app = Flask(__name__)

# Folder paths
UPLOAD_FOLDER = 'uploads'
CHARTS_FOLDER = 'static/charts'
DOWNLOAD_FOLDER = 'downloads'

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['CHARTS_FOLDER'] = CHARTS_FOLDER
app.config['DOWNLOAD_FOLDER'] = DOWNLOAD_FOLDER

# Allowed file extensions
ALLOWED_EXTENSIONS = {'xlsx'}

# Ensure folders exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(CHARTS_FOLDER, exist_ok=True)
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def process_data(df):
    df['Date'] = pd.to_datetime(df['Date'], dayfirst=True, errors='coerce')
    df['Description'] = df['Description'].astype(str)
    df['Debit'] = pd.to_numeric(df['Debit'], errors='coerce')
    df['Credit'] = pd.to_numeric(df['Credit'], errors='coerce')
    df['Balance'] = pd.to_numeric(df['Balance'], errors='coerce')

    df['Description_lower'] = df['Description'].str.lower()

    df['Talabat credit'] = df.apply(lambda x: x['Credit'] if 'inward' in x['Description_lower'] and 'talabat' in x['Description_lower'] else 0, axis=1)
    df['Snoonu credit'] = df.apply(lambda x: x['Credit'] if 'inward' in x['Description_lower'] and 'snoon' in x['Description_lower'] else 0, axis=1)
    df['Cash deposit'] = df.apply(lambda x: x['Credit'] if 'cash' in x['Description_lower'] and 'deposit' in x['Description_lower'] else 0, axis=1)
    df['Card Payout'] = df.apply(lambda x: x['Credit'] if all(k in x['Description_lower'] for k in ['internal', 'transfer', 'fullpayout']) else 0, axis=1)

    df['Card Purchases'] = df.apply(lambda x: x['Debit'] if x['Description_lower'].startswith('pos') else 0, axis=1)
    df['Bank charges'] = df.apply(lambda x: x['Debit'] if any(k in x['Description_lower'] for k in ['charge', 'fee', 'fees', 'pos rental']) else 0, axis=1)
    df['ATM Withdrawal'] = df.apply(lambda x: x['Debit'] if 'atm cash withdrawal' in x['Description_lower'] else 0, axis=1)
    df['WPS Transfer'] = df.apply(lambda x: x['Debit'] if 'wps salary' in x['Description_lower'] else 0, axis=1)
    df['Transfer'] = df.apply(lambda x: x['Debit'] if 'outward qatch' in x['Description_lower'] else 0, axis=1)

    df['Month'] = df['Date'].dt.to_period('M').astype(str)

    pivot = df.groupby('Month')[
        ['Talabat credit', 'Snoonu credit', 'Cash deposit', 'Card Payout',
         'Card Purchases', 'Bank charges', 'ATM Withdrawal', 'WPS Transfer', 'Transfer',
         'Debit', 'Credit']
    ].sum().round(2).reset_index()

    pivot['Credit Match Status'] = (
        (pivot['Talabat credit'] + pivot['Snoonu credit'] + pivot['Cash deposit'] + pivot['Card Payout']).round(2) == pivot['Credit'].round(2)
    )

    pivot['Debit Match Status'] = (
        (pivot['Card Purchases'] + pivot['Bank charges'] + pivot['ATM Withdrawal'] + pivot['WPS Transfer'] + pivot['Transfer']).round(2) == pivot['Debit'].round(2)
    )

    last_balances = df.groupby('Month')['Balance'].last().reset_index().rename(columns={'Balance': 'Last Balance'})
    pivot = pivot.merge(last_balances, on='Month', how='left')

    return df, pivot

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return redirect(request.url)
    file = request.files['file']

    if file.filename == '':
        return redirect(request.url)

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)

        try:
            df = pd.read_excel(filepath)
            df, pivot_table = process_data(df)

            df_filename = f"df_{filename.replace('.xlsx', '.csv')}"
            pivot_filename = f"pivot_{filename.replace('.xlsx', '.csv')}"

            df_filepath = os.path.join(app.config['DOWNLOAD_FOLDER'], df_filename)
            pivot_filepath = os.path.join(app.config['DOWNLOAD_FOLDER'], pivot_filename)
            df.to_csv(df_filepath, index=False)
            pivot_table.to_csv(pivot_filepath, index=False)

            for month in pivot_table['Month']:
                # Credit vs Debit Bar Chart
                fig, ax = plt.subplots()
                vals = [pivot_table.loc[pivot_table['Month'] == month, 'Credit'].values[0],
                        pivot_table.loc[pivot_table['Month'] == month, 'Debit'].values[0]]
                ax.bar(['Credit', 'Debit'], vals, color=['green', 'red'])
                for i, v in enumerate(vals):
                    ax.text(i, v + (v * 0.01), f'{v:.2f}', ha='center', va='bottom')
                plt.title(f'Total Credit vs Debit - {month}')
                plt.ylabel('Amount')
                plt.tight_layout()
                plt.savefig(os.path.join(app.config['CHARTS_FOLDER'], f"{month}_bar.png"))
                plt.close()

                # Credit Pie
                credit_labels = ['Talabat credit', 'Snoonu credit', 'Cash deposit', 'Card Payout']
                credit_values = pivot_table.loc[pivot_table['Month'] == month, credit_labels].values.flatten()
                if sum(credit_values) > 0:
                    fig, ax = plt.subplots()
                    ax.pie(credit_values, labels=credit_labels,
                           autopct=lambda pct: f'{pct:.1f}%\n({int(pct/100*sum(credit_values))})', startangle=90)
                    ax.axis('equal')
                    plt.title(f'Credit Split - {month}')
                    plt.tight_layout()
                    plt.savefig(os.path.join(app.config['CHARTS_FOLDER'], f"{month}_credit_pie.png"))
                    plt.close()

                # Debit Pie
                debit_labels = ['Card Purchases', 'Bank charges', 'ATM Withdrawal', 'WPS Transfer', 'Transfer']
                debit_values = pivot_table.loc[pivot_table['Month'] == month, debit_labels].values.flatten()
                if sum(debit_values) > 0:
                    fig, ax = plt.subplots()
                    ax.pie(debit_values, labels=debit_labels,
                           autopct=lambda pct: f'{pct:.1f}%\n({int(pct/100*sum(debit_values))})', startangle=90)
                    ax.axis('equal')
                    plt.title(f'Debit Split - {month}')
                    plt.tight_layout()
                    plt.savefig(os.path.join(app.config['CHARTS_FOLDER'], f"{month}_debit_pie.png"))
                    plt.close()

            return redirect(url_for('report', df_filename=df_filename, pivot_filename=pivot_filename))

        except Exception as e:
            return f"Error processing file: {e}"
    else:
        return 'Invalid file format'

@app.route('/report')
def report():
    pivot_filename = request.args.get('pivot_filename')
    df_filename = request.args.get('df_filename')
    pivot_path = os.path.join(app.config['DOWNLOAD_FOLDER'], pivot_filename)
    pivot_df = pd.read_csv(pivot_path)
    return render_template('report.html', 
                           months=pivot_df['Month'].tolist(), 
                           pivot_data=pivot_df.to_dict(orient='records'),
                           pivot_filename=pivot_filename,
                           df_filename=df_filename)

@app.route('/show_charts/<month>')
def show_charts(month):
    return render_template('charts.html', month=month)

@app.route('/download/<filename>')
def download_file(filename):
    return send_from_directory(app.config['DOWNLOAD_FOLDER'], filename, as_attachment=True)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
