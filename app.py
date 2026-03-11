import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
from datetime import date, datetime
import pandas as pd
import plotly.express as px
import io
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

# =========================
# Google Sheets 接続設定
# =========================
WORKSHEET_NAME = "sales"
SPREADSHEET_KEY = "14b762DqI4pMbS9Z3ECcrSg1oDywsP2Tpiae98QUbQbw"

scope = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

creds = Credentials.from_service_account_info(
    st.secrets["gcp_service_account"],
    scopes=scope
)

client = gspread.authorize(creds)
spreadsheet = client.open_by_key(SPREADSHEET_KEY)
sheet = spreadsheet.worksheet(WORKSHEET_NAME)

# =========================
# Streamlit 基本設定
# =========================
st.set_page_config(
    page_title="Nail Salon Sales",
    page_icon="💅",
    layout="centered",
    initial_sidebar_state="collapsed"
)

pdfmetrics.registerFont(UnicodeCIDFont("HeiseiKakuGo-W5"))

# =========================
# Google Sheets 初期化
# =========================
def init_sheet():
    headers = [
        "id",
        "customer_name",
        "reservation_type",
        "payment_method",
        "amount",
        "sale_date",
        "created_at"
    ]

    values = sheet.get_all_values()

    if not values:
        sheet.append_row(headers)
        return

    current_headers = values[0]

    if current_headers != headers:
        sheet.update("A1:G1", [headers])


def get_next_id(df: pd.DataFrame) -> int:
    if df.empty or "id" not in df.columns:
        return 1
    ids = pd.to_numeric(df["id"], errors="coerce").dropna()
    if ids.empty:
        return 1
    return int(ids.max()) + 1


# =========================
# データ読込
# =========================
@st.cache_data(ttl=2)
def load_data():
    records = sheet.get_all_records()

    if not records:
        return pd.DataFrame(columns=[
            "id",
            "customer_name",
            "reservation_type",
            "payment_method",
            "amount",
            "sale_date",
            "created_at"
        ])

    df = pd.DataFrame(records)

    expected_cols = [
        "id",
        "customer_name",
        "reservation_type",
        "payment_method",
        "amount",
        "sale_date",
        "created_at"
    ]
    for col in expected_cols:
        if col not in df.columns:
            df[col] = None

    df["id"] = pd.to_numeric(df["id"], errors="coerce")
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0).astype(int)
    df["sale_date"] = pd.to_datetime(df["sale_date"], errors="coerce")
    df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce")

    df = df.dropna(subset=["sale_date"]).copy()
    df = df.sort_values(["sale_date", "id"], ascending=False)

    return df


# =========================
# 追加
# =========================
def insert_sale(customer_name: str, reservation_type: str, payment_method: str, amount: int, sale_date: date):
    df = load_data()
    new_id = get_next_id(df)

    new_row = [
        new_id,
        customer_name,
        reservation_type,
        payment_method,
        amount,
        sale_date.strftime("%Y-%m-%d"),
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ]

    sheet.append_row(new_row, value_input_option="USER_ENTERED")
    load_data.clear()
    yearly_summary.clear()


# =========================
# 更新
# =========================
def update_sale(sale_id: int, customer_name: str, reservation_type: str, payment_method: str, amount: int, sale_date: date):
    values = sheet.get_all_values()

    if len(values) <= 1:
        return

    headers = values[0]
    id_idx = headers.index("id")

    target_row_number = None

    for i, row in enumerate(values[1:], start=2):
        if len(row) > id_idx and str(row[id_idx]) == str(sale_id):
            target_row_number = i
            break

    if target_row_number is None:
        return

    created_at_idx = headers.index("created_at")
    current_row = values[target_row_number - 1]
    created_at = current_row[created_at_idx] if len(current_row) > created_at_idx else ""

    updated_row = [
        sale_id,
        customer_name,
        reservation_type,
        payment_method,
        amount,
        sale_date.strftime("%Y-%m-%d"),
        created_at if created_at else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ]

    sheet.update(f"A{target_row_number}:G{target_row_number}", [updated_row])
    load_data.clear()
    yearly_summary.clear()


# =========================
# 削除
# =========================
def delete_sale(sale_id: int):
    values = sheet.get_all_values()

    if len(values) <= 1:
        return

    headers = values[0]
    id_idx = headers.index("id")

    target_row_number = None

    for i, row in enumerate(values[1:], start=2):
        if len(row) > id_idx and str(row[id_idx]) == str(sale_id):
            target_row_number = i
            break

    if target_row_number is not None:
        sheet.delete_rows(target_row_number)

    load_data.clear()
    yearly_summary.clear()


# =========================
# 集計
# =========================
def monthly_summary(year: int, month: int):
    df = load_data()
    if df.empty:
        return pd.DataFrame(), 0, pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    target = df[(df["sale_date"].dt.year == year) & (df["sale_date"].dt.month == month)].copy()
    if target.empty:
        return target, 0, pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    total = int(target["amount"].sum())

    by_type = target.groupby("reservation_type")["amount"].agg(["sum", "count"]).reset_index()
    by_type.columns = ["予約経路", "売上金額", "件数"]

    by_payment = target.groupby("payment_method")["amount"].agg(["sum", "count"]).reset_index()
    by_payment.columns = ["支払い方法", "売上金額", "件数"]

    by_name = target.groupby("customer_name", as_index=False)["amount"].sum().sort_values("amount", ascending=False)
    by_name.columns = ["お客様名", "売上金額"]

    return target, total, by_type, by_payment, by_name


@st.cache_data(ttl=2)
def yearly_summary(year: int):
    df = load_data()
    if df.empty:
        return pd.DataFrame(), 0, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    target = df[df["sale_date"].dt.year == year].copy()
    if target.empty:
        return target, 0, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    total = int(target["amount"].sum())

    by_type = target.groupby("reservation_type")["amount"].agg(["sum", "count"]).reset_index()
    by_type.columns = ["予約経路", "売上金額", "件数"]

    by_payment = target.groupby("payment_method")["amount"].agg(["sum", "count"]).reset_index()
    by_payment.columns = ["支払い方法", "売上金額", "件数"]

    by_month = target.groupby(target["sale_date"].dt.month)["amount"].sum().reset_index()
    by_month.columns = ["月", "売上金額"]
    by_month = by_month.sort_values("月")

    by_name = target.groupby("customer_name", as_index=False)["amount"].sum().sort_values("amount", ascending=False)
    by_name.columns = ["お客様名", "売上金額"]

    return target, total, by_type, by_payment, by_month, by_name


# =========================
# PDF
# =========================
def _draw_pdf_header(c, title: str, subtitle: str):
    c.setFont("HeiseiKakuGo-W5", 18)
    c.drawString(40, 800, title)
    c.setFont("HeiseiKakuGo-W5", 10)
    c.drawString(40, 782, subtitle)
    c.line(40, 775, 555, 775)


def _draw_pdf_lines(c, lines, start_y=750):
    y = start_y
    c.setFont("HeiseiKakuGo-W5", 10)
    for line in lines:
        if y < 50:
            c.showPage()
            c.setFont("HeiseiKakuGo-W5", 10)
            y = 800
        c.drawString(45, y, str(line))
        y -= 18


def build_monthly_pdf(year: int, month: int):
    month_df, month_total, month_by_type, month_by_payment, month_by_name = monthly_summary(year, month)
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)

    _draw_pdf_header(
        c,
        "ネイルサロン 月別売上レポート",
        f"対象: {year}年{month}月 / 作成日: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    )

    lines = [
        f"月の売上合計: ¥{month_total:,.0f}",
        f"件数: {len(month_df)}件",
        f"客単価: ¥{(month_total / len(month_df)) if len(month_df) else 0:,.0f}",
        "",
        "【予約経路ごとの内訳】"
    ]

    if month_by_type.empty:
        lines.append("データなし")
    else:
        for _, row in month_by_type.iterrows():
            lines.append(f"・{row['予約経路']}: ¥{int(row['売上金額']):,} / {int(row['件数'])}件")

    lines += ["", "【支払い方法ごとの内訳】"]
    if month_by_payment.empty:
        lines.append("データなし")
    else:
        for _, row in month_by_payment.iterrows():
            lines.append(f"・{row['支払い方法']}: ¥{int(row['売上金額']):,} / {int(row['件数'])}件")

    lines += ["", "【お客様別内訳】"]
    if month_by_name.empty:
        lines.append("データなし")
    else:
        for _, row in month_by_name.iterrows():
            lines.append(f"・{row['お客様名']}: ¥{int(row['売上金額']):,}")

    _draw_pdf_lines(c, lines)
    c.save()
    buffer.seek(0)
    return buffer.getvalue()


def build_yearly_pdf(year: int):
    year_df, year_total, year_by_type, year_by_payment, year_by_month, year_by_name = yearly_summary(year)
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)

    _draw_pdf_header(
        c,
        "ネイルサロン 年別売上レポート",
        f"対象: {year}年 / 作成日: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    )

    lines = [
        f"年の売上合計: ¥{year_total:,.0f}",
        f"件数: {len(year_df)}件",
        f"客単価: ¥{(year_total / len(year_df)) if len(year_df) else 0:,.0f}",
        "",
        "【予約経路ごとの内訳】"
    ]

    if year_by_type.empty:
        lines.append("データなし")
    else:
        for _, row in year_by_type.iterrows():
            lines.append(f"・{row['予約経路']}: ¥{int(row['売上金額']):,} / {int(row['件数'])}件")

    lines += ["", "【支払い方法ごとの内訳】"]
    if year_by_payment.empty:
        lines.append("データなし")
    else:
        for _, row in year_by_payment.iterrows():
            lines.append(f"・{row['支払い方法']}: ¥{int(row['売上金額']):,} / {int(row['件数'])}件")

    lines += ["", "【月ごとの売上】"]
    if year_by_month.empty:
        lines.append("データなし")
    else:
        for _, row in year_by_month.iterrows():
            lines.append(f"・{int(row['月'])}月: ¥{int(row['売上金額']):,}")

    lines += ["", "【お客様別年間内訳】"]
    if year_by_name.empty:
        lines.append("データなし")
    else:
        for _, row in year_by_name.iterrows():
            lines.append(f"・{row['お客様名']}: ¥{int(row['売上金額']):,}")

    _draw_pdf_lines(c, lines)
    c.save()
    buffer.seek(0)
    return buffer.getvalue()


# =========================
# 初期化
# =========================
init_sheet()

# =========================
# UI
# =========================
st.markdown(
    """
    <meta name="theme-color" content="#f6dbe7">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="default">
    <style>
    .stApp {
        background: linear-gradient(135deg, #fff7fb 0%, #fff1f7 50%, #fdf2ff 100%);
    }
    .main-title {
        font-size: 2rem;
        font-weight: 700;
        color: #5f3b57;
        margin-bottom: 0.2rem;
    }
    .sub-title {
        font-size: 0.95rem;
        color: #8b6d84;
        margin-bottom: 1.5rem;
    }
    .section-card {
        background: rgba(255,255,255,0.80);
        border-radius: 20px;
        padding: 16px 14px;
        box-shadow: 0 10px 30px rgba(169, 116, 151, 0.10);
        border: 1px solid rgba(255,255,255,0.7);
        margin-bottom: 14px;
    }
    .stButton > button, .stDownloadButton > button {
        width: 100%;
        border-radius: 14px;
        min-height: 48px;
        font-size: 1rem;
    }
    .stTextInput input, .stNumberInput input, div[data-baseweb="select"] > div {
        border-radius: 12px;
    }
    div[role="radiogroup"] {
        gap: 10px;
        flex-wrap: wrap;
    }
    header[data-testid="stHeader"] {
        visibility: hidden;
        height: 0;
    }
    div[data-testid="stToolbar"] {
        display: none;
    }
    #MainMenu {
        visibility: hidden;
    }
    footer {
        visibility: hidden;
    }
    .block-container {
        padding-top: 1rem;
        padding-bottom: 2rem;
        max-width: 680px;
    }
    @media (max-width: 768px) {
        .main-title {
            font-size: 1.6rem;
        }
        .sub-title {
            font-size: 0.9rem;
        }
        .section-card {
            padding: 14px 12px;
            border-radius: 18px;
        }
        .block-container {
            padding-top: 0.6rem;
            padding-left: 0.8rem;
            padding-right: 0.8rem;
            padding-bottom: 2rem;
        }
    }
    </style>
    """,
    unsafe_allow_html=True
)

st.markdown('<div class="main-title">💅 Nail Salon Sales Manager</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-title">おしゃれに、かんたんに、毎日の売上を管理</div>', unsafe_allow_html=True)
st.caption("iPhoneは共有ボタンから『ホーム画面に追加』、Androidはメニューから『ホーム画面に追加』でアプリっぽく使えます。")

tab1, tab2, tab3 = st.tabs(["➕ 売上入力・編集", "📅 月別集計", "📆 年別集計"])

with tab1:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.subheader("売上入力")
    st.caption("入力フロー：名前 → 予約経路 → 支払い方法 → 売上金額 → 完了")

    with st.form("sale_input_form", clear_on_submit=True):
        customer_name = st.text_input("① 名前を入力", placeholder="例：山田さん")
        reservation_type = st.radio(
            "② 予約経路を選択",
            ["友達", "ネイリー", "DM"],
            horizontal=True
        )
        payment_method = st.radio(
            "③ 支払い方法を選択",
            ["現金", "PayPay"],
            horizontal=True
        )
        amount = st.number_input("④ 売上金を入力", min_value=0, step=500, placeholder=7000)
        sale_date = st.date_input("日付", value=date.today())

        submitted = st.form_submit_button("⑤ 入力完了", use_container_width=True)

        if submitted:
            if not customer_name.strip():
                st.error("名前を入力してください。")
            elif amount <= 0:
                st.error("売上金は1円以上で入力してください。")
            else:
                insert_sale(customer_name.strip(), reservation_type, payment_method, int(amount), sale_date)
                st.success("売上を登録しました。")
                st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)

    df = load_data()

    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.subheader("最近の登録履歴")
    if df.empty:
        st.info("まだ売上データがありません。")
    else:
        recent = df.copy().sort_values(["sale_date", "id"], ascending=False).head(20)
        recent_display = recent[["sale_date", "customer_name", "reservation_type", "payment_method", "amount"]].copy()
        recent_display.columns = ["日付", "名前", "予約経路", "支払い方法", "売上金額"]
        recent_display["日付"] = recent_display["日付"].dt.strftime("%Y-%m-%d")
        recent_display["売上金額"] = recent_display["売上金額"].map(lambda x: f"¥{x:,.0f}")
        st.dataframe(recent_display, use_container_width=True, hide_index=True)
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.subheader("編集・削除")
    if df.empty:
        st.info("編集できるデータがまだありません。")
    else:
        edit_df = df.copy().sort_values(["sale_date", "id"], ascending=False)
        edit_df["label"] = edit_df.apply(
            lambda row: f'{row["sale_date"].strftime("%Y-%m-%d")} | {row["customer_name"]} | {row["reservation_type"]} | {row["payment_method"]} | ¥{row["amount"]:,.0f}',
            axis=1
        )
        selected_label = st.selectbox("編集・削除するデータを選択", edit_df["label"].tolist())
        selected_row = edit_df[edit_df["label"] == selected_label].iloc[0]

        with st.form("edit_sale_form"):
            edit_name = st.text_input("名前", value=selected_row["customer_name"])
            reservation_options = ["友達", "ネイリー", "DM"]
            payment_options = ["現金", "PayPay"]

            edit_reservation = st.radio(
                "予約経路",
                reservation_options,
                index=reservation_options.index(selected_row["reservation_type"]),
                horizontal=True
            )

            current_payment = selected_row["payment_method"] if selected_row["payment_method"] in payment_options else "現金"
            edit_payment = st.radio(
                "支払い方法",
                payment_options,
                index=payment_options.index(current_payment),
                horizontal=True
            )

            edit_amount = st.number_input("売上金額", min_value=0, step=500, value=int(selected_row["amount"]))
            edit_date = st.date_input("日付", value=selected_row["sale_date"].date())

            update_submitted = st.form_submit_button("更新する", use_container_width=True)
            delete_submitted = st.form_submit_button("削除する", use_container_width=True)

            if update_submitted:
                if not edit_name.strip():
                    st.error("名前を入力してください。")
                elif edit_amount <= 0:
                    st.error("売上金は1円以上で入力してください。")
                else:
                    update_sale(
                        int(selected_row["id"]),
                        edit_name.strip(),
                        edit_reservation,
                        edit_payment,
                        int(edit_amount),
                        edit_date
                    )
                    st.success("データを更新しました。")
                    st.rerun()

            if delete_submitted:
                delete_sale(int(selected_row["id"]))
                st.success("データを削除しました。")
                st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)

with tab2:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.subheader("月別集計")
    current = date.today()
    selected_year = st.number_input("年を選択", min_value=2020, max_value=2100, value=current.year, step=1)
    selected_month = st.selectbox("月を選択", list(range(1, 13)), index=current.month - 1)

    month_df, month_total, month_by_type, month_by_payment, month_by_name = monthly_summary(int(selected_year), int(selected_month))

    st.metric("月の売上合計", f"¥{month_total:,.0f}")
    st.metric("件数", f"{len(month_df)}件")
    st.metric("客単価", f"¥{(month_total / len(month_df)) if len(month_df) else 0:,.0f}")

    if not month_df.empty:
        monthly_pdf_selected = build_monthly_pdf(int(selected_year), int(selected_month))
        st.download_button(
            label=f"この月のレポートをPDFでダウンロード（{int(selected_year)}年{int(selected_month)}月）",
            data=monthly_pdf_selected,
            file_name=f"nail_salon_monthly_report_{int(selected_year)}_{int(selected_month)}.pdf",
            mime="application/pdf",
            use_container_width=True
        )
    st.markdown("</div>", unsafe_allow_html=True)

    if month_df.empty:
        st.info("この月のデータはありません。")
    else:
        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.markdown("**予約経路ごとの内訳**")
        display_type = month_by_type.copy()
        display_type["売上金額"] = display_type["売上金額"].map(lambda x: f"¥{x:,.0f}")
        st.dataframe(display_type, use_container_width=True, hide_index=True)
        fig_type = px.pie(month_by_type, names="予約経路", values="売上金額", hole=0.45)
        st.plotly_chart(fig_type, use_container_width=True, key=f"month_type_{selected_year}_{selected_month}")
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.markdown("**支払い方法ごとの内訳**")
        display_payment = month_by_payment.copy()
        display_payment["売上金額"] = display_payment["売上金額"].map(lambda x: f"¥{x:,.0f}")
        st.dataframe(display_payment, use_container_width=True, hide_index=True)
        fig_payment = px.pie(month_by_payment, names="支払い方法", values="売上金額", hole=0.45)
        st.plotly_chart(fig_payment, use_container_width=True, key=f"month_payment_{selected_year}_{selected_month}")
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.markdown("**お客様別の内訳**")
        display_name = month_by_name.copy()
        display_name["売上金額"] = display_name["売上金額"].map(lambda x: f"¥{x:,.0f}")
        st.dataframe(display_name, use_container_width=True, hide_index=True)
        st.markdown("</div>", unsafe_allow_html=True)

with tab3:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.subheader("年別集計")
    current = date.today()
    selected_year_for_yearly = st.number_input(
        "集計する年を選択",
        min_value=2020,
        max_value=2100,
        value=current.year,
        step=1,
        key="yearly_input"
    )

    year_df, year_total, year_by_type, year_by_payment, year_by_month, year_by_name = yearly_summary(
        int(selected_year_for_yearly)
    )

    st.metric("年の売上合計", f"¥{year_total:,.0f}")
    st.metric("件数", f"{len(year_df)}件")
    st.metric("客単価", f"¥{(year_total / len(year_df)) if len(year_df) else 0:,.0f}")

    if not year_df.empty:
        yearly_pdf_selected = build_yearly_pdf(int(selected_year_for_yearly))
        st.download_button(
            label=f"この年のレポートをPDFでダウンロード（{int(selected_year_for_yearly)}年）",
            data=yearly_pdf_selected,
            file_name=f"nail_salon_yearly_report_{int(selected_year_for_yearly)}.pdf",
            mime="application/pdf",
            use_container_width=True
        )
    st.markdown("</div>", unsafe_allow_html=True)

    if year_df.empty:
        st.info("この年のデータはありません。")
    else:
        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.markdown("**予約経路ごとの内訳**")
        display_year_type = year_by_type.copy()
        display_year_type["売上金額"] = display_year_type["売上金額"].map(lambda x: f"¥{x:,.0f}")
        st.dataframe(display_year_type, use_container_width=True, hide_index=True)
        fig_year_type = px.pie(year_by_type, names="予約経路", values="売上金額", hole=0.45)
        st.plotly_chart(fig_year_type, use_container_width=True, key=f"year_type_{selected_year_for_yearly}")
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.markdown("**支払い方法ごとの内訳**")
        display_year_payment = year_by_payment.copy()
        display_year_payment["売上金額"] = display_year_payment["売上金額"].map(lambda x: f"¥{x:,.0f}")
        st.dataframe(display_year_payment, use_container_width=True, hide_index=True)
        fig_year_payment = px.pie(year_by_payment, names="支払い方法", values="売上金額", hole=0.45)
        st.plotly_chart(fig_year_payment, use_container_width=True, key=f"year_payment_{selected_year_for_yearly}")
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.markdown("**月ごとの売上**")
        display_month = year_by_month.copy()
        display_month["売上金額"] = display_month["売上金額"].map(lambda x: f"¥{x:,.0f}")
        st.dataframe(display_month, use_container_width=True, hide_index=True)
        fig_month = px.bar(year_by_month, x="月", y="売上金額")
        st.plotly_chart(fig_month, use_container_width=True, key=f"year_month_{selected_year_for_yearly}")
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.markdown("**お客様別の年間内訳**")
        display_year_name = year_by_name.copy()
        display_year_name["売上金額"] = display_year_name["売上金額"].map(lambda x: f"¥{x:,.0f}")
        st.dataframe(display_year_name, use_container_width=True, hide_index=True)
        st.markdown("</div>", unsafe_allow_html=True)

