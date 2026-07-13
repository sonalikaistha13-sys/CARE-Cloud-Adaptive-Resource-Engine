"""CARE — Cloud Adaptive Resource Engine dashboard."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Final

import random
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from database_manager import (
    CPU_FAULTY,
    CPU_WARNING,
    CloudServer,
    DISK_FAULTY,
    DISK_WARNING,
    RAM_FAULTY,
    RAM_WARNING,
    ServerStatus,
    fetch_all_servers,
    initialize_database,
    refresh_server_metrics,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REFRESH_SECONDS: Final[int] = 30


@dataclass(frozen=True)
class DashboardKPIs:
    healthy_servers: int
    faulty_servers: int
    running_vms: int
    active_tasks: int


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------


def compute_kpis(servers: list[CloudServer]) -> DashboardKPIs:
    """Aggregate dashboard KPI values from server list."""
    return DashboardKPIs(
        healthy_servers=sum(1 for s in servers if s.status == ServerStatus.HEALTHY),
        faulty_servers=sum(1 for s in servers if s.status == ServerStatus.FAULTY),
        running_vms=sum(s.running_vms for s in servers),
        active_tasks=sum(s.active_tasks for s in servers),
    )


def servers_to_dataframe(servers: list[CloudServer]) -> pd.DataFrame:
    """Convert server objects to a display-ready DataFrame."""
    records = [
        {
            "Server ID": s.server_id,
            "CPU Usage (%)": s.cpu_usage,
            "RAM Usage (%)": s.ram_usage,
            "Disk Usage (%)": s.disk_usage,
            "Network (Mbps)": s.network_usage,
            "Status": s.status.value,
            "Running VMs": s.running_vms,
            "Active Tasks": s.active_tasks,
        }
        for s in servers
    ]
    return pd.DataFrame(records)


# ---------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------


def inject_custom_css() -> None:
    """Apply dashboard styling."""
    st.markdown(
        """
        <style>
            .block-container {
                padding-top: 1.5rem;
                padding-bottom: 2rem;
                max-width: 1400px;
            }
            .care-header {
                font-size: 2rem;
                font-weight: 700;
                margin-bottom: 0.15rem;
                color: #0f172a;
            }
            .care-subtitle {
                color: #64748b;
                font-size: 1rem;
                margin-bottom: 1.75rem;
            }
            div[data-testid="stMetric"] {
                background: linear-gradient(135deg, #ffffff 0%, #f8fafc 100%);
                border: 1px solid #e2e8f0;
                border-radius: 12px;
                padding: 1rem 1.25rem;
                box-shadow: 0 1px 3px rgba(15, 23, 42, 0.06);
            }
            div[data-testid="stMetric"] label {
                color: #475569 !important;
                font-weight: 600;
            }
            div[data-testid="stMetric"] [data-testid="stMetricValue"] {
                color: #0f172a;
                font-weight: 700;
            }
            .section-title {
                font-size: 1.1rem;
                font-weight: 600;
                color: #1e293b;
                margin: 1.5rem 0 0.75rem 0;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_header() -> None:
    """Render page title and timestamp."""
    st.markdown('<p class="care-header">☁️ CARE — Cloud Adaptive Resource Engine</p>', unsafe_allow_html=True)
    st.markdown(
        '<p class="care-subtitle">Real-time cloud infrastructure monitoring dashboard</p>',
        unsafe_allow_html=True,
    )
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    st.caption(f"Last updated: {timestamp}")


def render_kpi_cards(kpis: DashboardKPIs) -> None:
    """Render four KPI metric cards."""
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric(label="Healthy Servers", value=kpis.healthy_servers, delta="online")
    with col2:
        st.metric(
            label="Faulty Servers",
            value=kpis.faulty_servers,
            delta="- action needed" if kpis.faulty_servers else "all clear",
            delta_color="inverse" if kpis.faulty_servers else "off",
        )
    with col3:
        st.metric(label="Running VMs", value=kpis.running_vms)
    with col4:
        st.metric(label="Active Tasks", value=kpis.active_tasks)


def _status_color(status: str) -> str:
    palette = {
        ServerStatus.HEALTHY.value: "#22c55e",
        ServerStatus.WARNING.value: "#f59e0b",
        ServerStatus.FAULTY.value: "#ef4444",
    }
    return palette.get(status, "#94a3b8")


def build_usage_bar_chart(
    df: pd.DataFrame,
    metric_column: str,
    title: str,
    color: str,
) -> go.Figure:
    """Build a horizontal bar chart for a usage metric."""
    chart_df = df.sort_values(metric_column, ascending=True)

    fig = px.bar(
        chart_df,
        x=metric_column,
        y="Server ID",
        orientation="h",
        title=title,
        color=metric_column,
        color_continuous_scale=[color, "#ef4444"],
        range_color=[0, 100],
        text=metric_column,
    )
    fig.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
    fig.update_layout(
        height=380,
        margin=dict(l=10, r=10, t=50, b=10),
        coloraxis_showscale=False,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(range=[0, 105], title="Usage (%)"),
        yaxis=dict(title=""),
        font=dict(family="Inter, sans-serif", size=12),
    )
    return fig


def render_charts(df: pd.DataFrame) -> None:
    """Render CPU and RAM Plotly charts side by side."""
    st.markdown('<p class="section-title">Resource Utilization</p>', unsafe_allow_html=True)

    col_cpu, col_ram = st.columns(2)

    with col_cpu:
        cpu_fig = build_usage_bar_chart(
            df,
            metric_column="CPU Usage (%)",
            title="CPU Usage by Server",
            color="#3b82f6",
        )
        st.plotly_chart(cpu_fig, use_container_width=True)

    with col_ram:
        ram_fig = build_usage_bar_chart(
            df,
            metric_column="RAM Usage (%)",
            title="RAM Usage by Server",
            color="#8b5cf6",
        )
        st.plotly_chart(ram_fig, use_container_width=True)


def _style_status_cell(value: str) -> str:
    color = _status_color(value)
    return (
        f"background-color: {color}22; color: {color}; "
        f"font-weight: 600; border-radius: 6px;"
    )


def render_server_table(df: pd.DataFrame) -> None:
    """Render styled server information table."""
    st.markdown('<p class="section-title">Server Inventory</p>', unsafe_allow_html=True)

    styled = df.style.map(_style_status_cell, subset=["Status"]).format(
        {
            "CPU Usage (%)": "{:.1f}",
            "RAM Usage (%)": "{:.1f}",
            "Disk Usage (%)": "{:.1f}",
            "Network (Mbps)": "{:.1f}",
        }
    )
    st.dataframe(styled, use_container_width=True, hide_index=True)


def render_server_cards(df: pd.DataFrame) -> None:
    """Render compact server cards in a grid."""
    st.markdown('<p class="section-title">Server Overview</p>', unsafe_allow_html=True)

    columns = st.columns(5)
    for index, row in df.iterrows():
        col = columns[index % 5]
        status = row["Status"]
        border_color = _status_color(status)

        with col:
            st.markdown(
                f"""
                <div style="
                    border: 1px solid #e2e8f0;
                    border-left: 4px solid {border_color};
                    border-radius: 10px;
                    padding: 0.85rem 1rem;
                    margin-bottom: 0.75rem;
                    background: #ffffff;
                    box-shadow: 0 1px 2px rgba(15,23,42,0.05);
                ">
                    <div style="font-weight:700;color:#0f172a;">{row['Server ID']}</div>
                    <div style="font-size:0.85rem;color:#64748b;margin-top:0.35rem;">
                        CPU: {row['CPU Usage (%)']:.1f}% &nbsp;|&nbsp; RAM: {row['RAM Usage (%)']:.1f}%
                    </div>
                    <div style="font-size:0.85rem;color:#64748b;">
                        Disk: {row['Disk Usage (%)']:.1f}% &nbsp;|&nbsp; Net: {row['Network (Mbps)']:.1f} Mbps
                    </div>
                    <div style="margin-top:0.5rem;font-size:0.8rem;font-weight:600;color:{border_color};">
                        ● {status}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )


def render_sidebar() -> None:
    """Render sidebar controls."""
    with st.sidebar:
        st.header("Controls")
        st.markdown("Configure dashboard behavior and refresh simulated metrics.")

        st.toggle(
            "Auto-refresh data",
            value=True,
            key="auto_refresh",
            help=f"Regenerate metrics every {REFRESH_SECONDS} seconds.",
        )
        if st.session_state.get("auto_refresh", True):
            st.caption(f"Metrics refresh every {REFRESH_SECONDS} seconds.")

        if st.button("Refresh Now", use_container_width=True):
            st.session_state["seed"] = random.randint(0, 999_999)
            st.rerun()

        st.divider()
        st.subheader("Thresholds")
        st.markdown(
            f"""
            - **Warning:** CPU ≥ {CPU_WARNING}% · RAM ≥ {RAM_WARNING}% · Disk ≥ {DISK_WARNING}%
            - **Faulty:** CPU ≥ {CPU_FAULTY}% · RAM ≥ {RAM_FAULTY}% · Disk ≥ {DISK_FAULTY}%
            """
        )

        st.divider()
        st.caption("CARE v0.1 — simulated data, no database connected.")



def load_dashboard_data() -> tuple[list[CloudServer], DashboardKPIs, pd.DataFrame]:
    """Load dashboard data."""
    initialize_database()

    if "seed" not in st.session_state:
        st.session_state["seed"] = random.randint(0, 999_999)

    random.seed(st.session_state["seed"])

    refresh_server_metrics()
    servers = fetch_all_servers()

    return servers, compute_kpis(servers), servers_to_dataframe(servers)


def render_dashboard() -> None:
    """Render all dashboard sections."""
    servers, kpis, df = load_dashboard_data()
    render_header()
    render_kpi_cards(kpis)
    render_server_cards(df)
    render_charts(df)
    render_server_table(df)


@st.fragment(run_every=f"{REFRESH_SECONDS}s")
def render_auto_refresh_dashboard() -> None:
    """Periodically refresh metrics when auto-refresh is enabled."""
    if st.session_state.get("auto_refresh", True):
        st.session_state["seed"] = random.randint(0, 999_999)
    render_dashboard()


# ---------------------------------------------------------------------------
# Application entry point
# ---------------------------------------------------------------------------


def main() -> None:
    st.set_page_config(
        page_title="CARE Dashboard",
        page_icon="☁️",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    inject_custom_css()
    render_sidebar()

    if st.session_state.get("auto_refresh", True):
        render_auto_refresh_dashboard()
    else:
        render_dashboard()


if __name__ == "__main__":
    main()
