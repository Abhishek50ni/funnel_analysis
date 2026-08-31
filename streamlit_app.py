"""
E-Commerce Product Analytics & Conversion Funnel Analysis
Streamlit App — Phases 12 & 13

Run with: streamlit run streamlit_app.py
Requires: pip install streamlit sqlalchemy psycopg2-binary pandas plotly
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="E-Commerce Funnel Analytics",
    page_icon="📊",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Sidebar: DB connection
# ---------------------------------------------------------------------------
st.sidebar.title("⚙️ Database Connection")
db_host = st.sidebar.text_input("Host", value="localhost")
db_port = st.sidebar.text_input("Port", value="5432")
db_name = st.sidebar.text_input("Database", value="funnel_analysis")
db_user = st.sidebar.text_input("Username", value="postgres")
db_password = st.sidebar.text_input("Password", type="password")

connect_clicked = st.sidebar.button("Connect")

if "engine" not in st.session_state:
    st.session_state.engine = None

if connect_clicked:
    try:
        conn_url = URL.create(
            drivername="postgresql+psycopg2",
            username=db_user,
            password=db_password,  # URL.create safely escapes special characters like @
            host=db_host,
            port=int(db_port),
            database=db_name,
        )
        st.session_state.engine = create_engine(conn_url)
        with st.session_state.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        st.sidebar.success("Connected ✅")
    except Exception as e:
        st.session_state.engine = None
        st.sidebar.error(f"Connection failed: {e}")

engine = st.session_state.engine

st.sidebar.divider()
page = st.sidebar.radio(
    "Navigate",
    ["🏠 Home", "🔍 EDA", "🔻 Funnel", "👥 Customers", "📦 Products", "💡 Recommendations"],
)

# ---------------------------------------------------------------------------
# Cached query helper
# ---------------------------------------------------------------------------
@st.cache_data(ttl=600)
def run_query(_engine, query):
    with _engine.connect() as conn:
        return pd.read_sql(text(query), conn)


def require_connection():
    if engine is None:
        st.warning("👈 Connect to your Postgres database in the sidebar first.")
        st.stop()


# ---------------------------------------------------------------------------
# PAGE: HOME
# ---------------------------------------------------------------------------
if page == "🏠 Home":
    st.title("📊 E-Commerce Product Analytics")
    st.caption("Conversion Funnel Analysis — RetailRocket Dataset")

    st.markdown(
        """
        This dashboard analyzes user behavior across the purchase funnel to answer:
        **Where are users dropping? Why? Which users convert best? What should we build next?**
        """
    )

    require_connection()

    col1, col2, col3, col4 = st.columns(4)

    kpi_query = """
        SELECT
            COUNT(DISTINCT visitorid) AS total_visitors,
            COUNT(DISTINCT session_id) AS total_sessions,
            COUNT(*) FILTER (WHERE funnel_stage = 'Purchase') AS total_purchases,
            ROUND(100.0 * COUNT(DISTINCT visitorid) FILTER (WHERE funnel_stage = 'Purchase')
                / COUNT(DISTINCT visitorid), 2) AS conversion_pct
        FROM events;
    """
    kpis = run_query(engine, kpi_query).iloc[0]

    col1.metric("Total Visitors", f"{int(kpis['total_visitors']):,}")
    col2.metric("Total Sessions", f"{int(kpis['total_sessions']):,}")
    col3.metric("Total Purchases", f"{int(kpis['total_purchases']):,}")
    col4.metric("Visitor → Purchase Rate", f"{kpis['conversion_pct']}%")

    st.divider()
    st.subheader("Headline Findings")
    st.markdown(
        """
        - 🚨 **79.6% of sessions bounce** after a single event
        - 🚨 **Only 1.98%** of product views ever result in an Add to Cart — the biggest funnel leak
        - ✅ Once in cart, **26.3%** convert to purchase — checkout itself is comparatively healthy
        - 📉 **Week-1 retention is ~3-4%** across every cohort — value capture happens in session 1 or not at all
        """
    )

# ---------------------------------------------------------------------------
# PAGE: EDA
# ---------------------------------------------------------------------------
elif page == "🔍 EDA":
    st.title("🔍 Exploratory Data Analysis")
    require_connection()

    tab1, tab2, tab3 = st.tabs(["Time Patterns", "Session Behavior", "Category Breakdown"])

    with tab1:
        st.subheader("Events by Hour of Day")
        hourly = run_query(engine, """
            SELECT EXTRACT(HOUR FROM event_timestamp) AS hour_of_day, COUNT(*) AS event_count
            FROM events GROUP BY hour_of_day ORDER BY hour_of_day;
        """)
        fig = px.line(hourly, x="hour_of_day", y="event_count", markers=True,
                       title="Traffic Pattern by Hour")
        st.plotly_chart(fig, use_container_width=True)

        st.subheader("Events by Day of Week")
        dow = run_query(engine, """
            SELECT TO_CHAR(event_timestamp, 'Day') AS day_of_week, COUNT(*) AS event_count
            FROM events GROUP BY day_of_week, EXTRACT(ISODOW FROM event_timestamp)
            ORDER BY EXTRACT(ISODOW FROM event_timestamp);
        """)
        fig = px.bar(dow, x="day_of_week", y="event_count", title="Traffic by Day of Week")
        st.plotly_chart(fig, use_container_width=True)

    with tab2:
        st.subheader("Bounce Rate")
        bounce = run_query(engine, """
            SELECT ROUND(100.0 * (
                SELECT COUNT(*) FROM (SELECT session_id FROM events GROUP BY session_id HAVING COUNT(*)=1) b
            ) / COUNT(DISTINCT session_id), 2) AS bounce_rate_pct
            FROM events;
        """).iloc[0]["bounce_rate_pct"]
        st.metric("Sessions with only 1 event", f"{bounce}%")

        st.subheader("Sessions per Visitor Distribution")
        sess_dist = run_query(engine, """
            SELECT session_count, COUNT(*) AS num_visitors FROM (
                SELECT visitorid, COUNT(DISTINCT session_id) AS session_count
                FROM events GROUP BY visitorid
            ) t WHERE session_count <= 15 GROUP BY session_count ORDER BY session_count;
        """)
        fig = px.bar(sess_dist, x="session_count", y="num_visitors",
                      title="How Many Sessions Do Visitors Have?")
        st.plotly_chart(fig, use_container_width=True)

    with tab3:
        st.subheader("Top 10 Categories by Views")
        cat_views = run_query(engine, """
            SELECT categoryid, COUNT(*) AS views FROM events
            WHERE funnel_stage = 'Product View' AND categoryid != 'unknown'
            GROUP BY categoryid ORDER BY views DESC LIMIT 10;
        """)
        fig = px.bar(cat_views, x="categoryid", y="views", title="Most-Viewed Categories")
        st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------------------------
# PAGE: FUNNEL
# ---------------------------------------------------------------------------
elif page == "🔻 Funnel":
    st.title("🔻 Conversion Funnel")
    require_connection()

    funnel_data = run_query(engine, """
        SELECT funnel_stage, COUNT(*) AS event_count
        FROM events GROUP BY funnel_stage;
    """)
    order = ["Product View", "Add to Cart", "Purchase"]
    funnel_data["funnel_stage"] = pd.Categorical(funnel_data["funnel_stage"], categories=order, ordered=True)
    funnel_data = funnel_data.sort_values("funnel_stage")

    fig = go.Figure(go.Funnel(
        y=funnel_data["funnel_stage"],
        x=funnel_data["event_count"],
        textposition="inside",
        textinfo="value+percent initial",
    ))
    fig.update_layout(title="Product View → Add to Cart → Purchase")
    st.plotly_chart(fig, use_container_width=True)

    col1, col2 = st.columns(2)
    views = int(funnel_data.loc[funnel_data.funnel_stage == "Product View", "event_count"].iloc[0])
    carts = int(funnel_data.loc[funnel_data.funnel_stage == "Add to Cart", "event_count"].iloc[0])
    purchases = int(funnel_data.loc[funnel_data.funnel_stage == "Purchase", "event_count"].iloc[0])

    col1.metric("View → Cart Conversion", f"{100*carts/views:.2f}%", help="The biggest leak")
    col2.metric("Cart → Purchase Conversion", f"{100*purchases/carts:.2f}%")

    st.subheader("Worst-Performing Categories (High Views, Zero Purchases)")
    worst = run_query(engine, """
        SELECT categoryid,
            COUNT(*) FILTER (WHERE funnel_stage = 'Product View') AS views,
            COUNT(*) FILTER (WHERE funnel_stage = 'Purchase') AS purchases
        FROM events WHERE categoryid != 'unknown'
        GROUP BY categoryid
        HAVING COUNT(*) FILTER (WHERE funnel_stage = 'Product View') >= 100
        ORDER BY purchases ASC, views DESC LIMIT 10;
    """)
    st.dataframe(worst, use_container_width=True)

# ---------------------------------------------------------------------------
# PAGE: CUSTOMERS
# ---------------------------------------------------------------------------
elif page == "👥 Customers":
    st.title("👥 Customer Segmentation & Retention")
    require_connection()

    st.subheader("Visitor Segments")
    seg = run_query(engine, """
        SELECT behavior_segment, COUNT(*) AS num_visitors
        FROM visitor_segments GROUP BY behavior_segment ORDER BY num_visitors DESC;
    """)
    fig = px.pie(seg, names="behavior_segment", values="num_visitors",
                 title="Visitor Segments (Behavior-Based)")
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("Engagement by Segment")
    eng = run_query(engine, """
        SELECT behavior_segment,
               ROUND(AVG(session_count), 2) AS avg_sessions,
               ROUND(AVG(view_count), 2) AS avg_views,
               ROUND(AVG(cart_count), 2) AS avg_cart_adds
        FROM visitor_segments GROUP BY behavior_segment ORDER BY avg_sessions DESC;
    """)
    st.dataframe(eng, use_container_width=True)

    st.subheader("Weekly Cohort Retention Heatmap")
    retention = run_query(engine, """
        WITH cohort_sizes AS (
            SELECT cohort_week, COUNT(DISTINCT visitorid) AS cohort_size
            FROM visitor_cohorts GROUP BY cohort_week
        ),
        retention AS (
            SELECT cohort_week, week_number, COUNT(DISTINCT visitorid) AS active_visitors
            FROM cohort_activity GROUP BY cohort_week, week_number
        )
        SELECT r.cohort_week, r.week_number,
               ROUND(100.0 * r.active_visitors / cs.cohort_size, 2) AS retention_pct
        FROM retention r JOIN cohort_sizes cs ON r.cohort_week = cs.cohort_week
        WHERE r.week_number BETWEEN 0 AND 8
        ORDER BY r.cohort_week, r.week_number;
    """)
    pivot = retention.pivot(index="cohort_week", columns="week_number", values="retention_pct")
    fig = px.imshow(pivot, text_auto=True, aspect="auto", color_continuous_scale="Blues",
                     title="Retention % by Cohort Week")
    st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------------------------
# PAGE: PRODUCTS
# ---------------------------------------------------------------------------
elif page == "📦 Products":
    st.title("📦 Product Performance")
    require_connection()

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Top 10 Most-Viewed Products")
        top_viewed = run_query(engine, """
            SELECT itemid, COUNT(*) AS views FROM events
            WHERE funnel_stage = 'Product View' GROUP BY itemid ORDER BY views DESC LIMIT 10;
        """)
        st.dataframe(top_viewed, use_container_width=True)

    with col2:
        st.subheader("Top 10 Most-Purchased Products")
        top_purchased = run_query(engine, """
            SELECT itemid, COUNT(*) AS purchases FROM events
            WHERE funnel_stage = 'Purchase' GROUP BY itemid ORDER BY purchases DESC LIMIT 10;
        """)
        st.dataframe(top_purchased, use_container_width=True)

    st.subheader("Best-Converting Products (min. 50 views)")
    best_conv = run_query(engine, """
        SELECT itemid,
            COUNT(*) FILTER (WHERE funnel_stage = 'Product View') AS views,
            COUNT(*) FILTER (WHERE funnel_stage = 'Purchase') AS purchases,
            ROUND(100.0 * COUNT(*) FILTER (WHERE funnel_stage = 'Purchase') /
                  NULLIF(COUNT(*) FILTER (WHERE funnel_stage = 'Product View'), 0), 2) AS conversion_pct
        FROM events GROUP BY itemid
        HAVING COUNT(*) FILTER (WHERE funnel_stage = 'Product View') >= 50
        ORDER BY conversion_pct DESC LIMIT 10;
    """)
    st.dataframe(best_conv, use_container_width=True)

# ---------------------------------------------------------------------------
# PAGE: RECOMMENDATIONS
# ---------------------------------------------------------------------------
elif page == "💡 Recommendations":
    st.title("💡 Product Recommendations")

    st.markdown(
        """
        ### 🎯 Finding #1: 98% of product views never reach Add to Cart
        This is the single largest leak in the funnel — far bigger than checkout abandonment.

        **Recommendations:**
        - Audit zero-purchase, high-traffic categories for pricing, imagery, and stock accuracy
        - Improve search/recommendation relevance so traffic sees genuinely fitting products
        - Add social proof (reviews, ratings) near the Add to Cart button

        ---

        ### 🎯 Finding #2: 79.6% of sessions bounce after one event
        Combined with 97.45% of visitors falling into the "Browser Only" segment, this points to
        an acquisition/relevance mismatch, not a UX friction problem within the site.

        **Recommendations:**
        - Review traffic sources — are ads/links setting accurate expectations?
        - A/B test product page relevance improvements (see Phase 11, Test 2) before checkout changes

        ---

        ### 🎯 Finding #3: Week-1 retention is only 3-4% across every cohort
        Value capture is almost entirely a first-session phenomenon.

        **Recommendations:**
        - Invest in first-session experience (search quality, personalization, page load speed)
        - Consider a returning-visitor incentive (email capture, retargeting) to convert the
          large one-time-visitor pool

        ---

        ### 🎯 Finding #4: Checkout is comparatively healthy (26.3% Cart → Purchase)
        **Recommendation:** Don't over-invest here — resources are better spent upstream at the
        product page / relevance layer identified above.
        """
    )