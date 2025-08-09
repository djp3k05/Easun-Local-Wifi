def _split(payload: str) -> list[str]:
    return payload.strip("()\r").split()

# ---------- QPIGS (real‑time status) ----------
def parse_qpigs(resp: str) -> dict:
    """
    Easun SMW inverters follow the 25‑field PI‑17 layout.
    Index ↔ meaning table is in every Voltronic PI‑17 spec.
    Only the fields required by the integration are decoded here.
    """
    v = _split(resp)
    return {
        "grid_voltage"        : float(v[0]),
        "grid_frequency"      : float(v[1]),
        "output_voltage"      : float(v[2]),
        "output_frequency"    : float(v[3]),
        "output_apparent_pow" : int(v[4]),
        "output_active_pow"   : int(v[5]),
        "load_percent"        : int(v[6]),
        "battery_voltage"     : float(v[8]),
        "battery_chg_current" : int(v[9]),
        "battery_soc"         : int(v[10]),
        "inverter_temp"       : int(v[11]),
        "pv_current"          : float(v[12]),
        "pv_voltage"          : float(v[13]),
        "pv_power"            : int(v[19]),   # field 19 in SMW = PV input power W
    }

# ---------- QMOD (operating mode) ----------
def parse_qmod(resp: str) -> str:
    """
    QMOD returns one digit code inside parentheses, e.g. “(B)” or “(2)”.
    We keep the raw char – the HA entity shows a nice human string.
    """
    return resp.strip("()\r")

# ---------- QPIRI, QBEQI, QDOP ----------
# You already have detailed parsers in models.py – import and re‑use them:
from .models import parse_qpiri_response as parse_qpiri
from .models import parse_qbeqi_response as parse_qbeqi
from .models import parse_qdop_response as parse_qdop
