import io
import json
import logging
import os
import shutil
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import anthropic
import pandas as pd
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

load_dotenv()

STORAGE_PATH = Path("data/storage.json")
BACKUP_PATH  = Path("data/storage_backup.json")
EMPTY_STORAGE: dict = {"clients": {}, "uploads": [], "current_week": None}
MAX_WEEKS_PER_CLIENT = 12

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

COLUMN_MAP: dict[str, list[str]] = {
    "timestamp": [
        "marcaj de timp",
        "timestamp", "marca de timp", "data și ora", "data si ora",
    ],
    "date_col": [
        "data (ziua analizată)", "data (ziua analizata)",
        "data zilei",
    ],
    "email": [
        "adresă de e-mail", "adresa de e-mail",
        "email", "email address", "adresă de email", "adresa de email",
    ],
    "name": [
        "nume si prenume", "nume și prenume",
        "name+surname", "name surname", "nume prenume", "nume+prenume",
        "numele și prenumele", "numele si prenumele",
    ],
    "breakfast": [
        "mic dejun: la ce ora l-ai luat? ,ce ai mancat/baut?, cum te-ai simtit inainte sa mananci?, cum te-ai simtit dupa ce ai mancat?:",
        "mic dejun: la ce oră l-ai luat? ,ce ai mâncat/băut?",
        "mic dejun: la ce ora l-ai luat? ,ce ai mancat/baut?",
        "breakfast", "mic dejun", "micul dejun",
    ],
    "breakfast_before": [],
    "breakfast_after": [],
    "lunch": [
        "pranz: la ce ora l-ai luat? ,ce ai mancat/baut?, cum te-ai simtit inainte sa mananci?, cum te-ai simtit dupa ce ai mancat?:",
        "prânz: la ce oră l-ai luat? ,ce ai mâncat/băut?",
        "pranz: la ce ora l-ai luat? ,ce ai mancat/baut?",
        "lunch", "prânz", "pranz",
    ],
    "lunch_before": [],
    "lunch_after": [],
    "dinner": [
        "cina: la ce ora l-ai luat? ,ce ai mancat/baut?, cum te-ai simtit inainte sa mananci?, cum te-ai simtit dupa ce ai mancat?:",
        "cina: la ce oră l-ai luat? ,ce ai mâncat/băut?",
        "cina: la ce ora l-ai luat? ,ce ai mancat/baut?",
        "dinner", "cină", "cina",
    ],
    "dinner_before": [],
    "dinner_after": [],
    "snack": [
        "gustare: la ce ora ai luat-o? ,ce ai mancat/baut?, cum te-ai simtit inainte sa mananci?, cum te-ai simtit dupa ce ai mancat?:",
        "gustare: la ce oră ai luat-o? ,ce ai mâncat/băut?",
        "gustare: la ce ora ai luat-o? ,ce ai mancat/baut?",
        "snack", "gustare",
    ],
    "snack_before": [],
    "snack_after": [],
    "transit": [
        "tranzit intestinal/scaun: tranzit intestinal/scaun: la ce oră? , consistență ( de exemplu, bucăți mici, solid, apos etc.), ați simțit că v-ați golit complet intestinul?, miros( ușor, mediu, puternic? , culoare? ( maro deschis, maro mediu, maro închis, negru etc.):",
        "tranzit intestinal/scaun: tranzit intestinal/scaun: la ce ora? , consistenta ( de exemplu, bucati mici, solid, apos etc.), ati simtit ca v-ati golit complet intestinul?, miros( usor, mediu, puternic? , culoare? ( maro deschis, maro mediu, maro inchis, negru etc.):",
        "intestinal transit", "tranzit intestinal", "tranzitul intestinal", "tranzit",
    ],
    "exercise": [
        "exercitii fizice: ai făcut miscare? (plimbare etc), cât timp?, cum te-ai simțit după ce ai făcut miscare?:",
        "exercitii fizice: ai facut miscare? (plimbare etc), cat timp?, cum te-ai simtit dupa ce ai facut miscare?:",
        "exercise", "exerciții fizice", "exercitii fizice", "mișcare", "miscare",
    ],
    "mindful_eating": [
        "ai mancat astazi mai lent cel putin o masa? (da/nu) respirând adânc înainte de a mâncare, recunoscătoare față de mâncare, vizualizând nutrienții etc, cum te-ai simțit?:",
        "ai mancat astazi mai lent cel putin o masa? (da/nu) respirand adanc inainte de a mancare, recunoscatoare fata de mancare, vizualizand nutrientii etc, cum te-ai simtit?:",
        "ai mancat astazi mai lent cel putin o masa?",
        "mindful eating", "alimentație conștientă",
    ],
}

REQUIRED_COLUMNS = {"email", "breakfast", "lunch", "dinner"}

MEAL_TEXT_MAX_CHARS = 300


app = FastAPI(title="Nutrition Feedback Assistant")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _read_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_storage() -> dict:
    STORAGE_PATH.parent.mkdir(parents=True, exist_ok=True)

    if STORAGE_PATH.exists():
        try:
            return _read_json(STORAGE_PATH)
        except (json.JSONDecodeError, OSError) as e:
            logging.warning("storage.json unreadable (%s) — attempting restore from backup.", e)

    if BACKUP_PATH.exists():
        try:
            data = _read_json(BACKUP_PATH)
            shutil.copy2(BACKUP_PATH, STORAGE_PATH)
            logging.warning("Restored storage.json from backup.")
            return data
        except (json.JSONDecodeError, OSError) as e:
            logging.error("Backup also unreadable (%s) — starting fresh.", e)

    empty = EMPTY_STORAGE.copy()
    save_storage(empty)
    return empty


def save_storage(data: dict) -> None:
    STORAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if STORAGE_PATH.exists():
        shutil.copy2(STORAGE_PATH, BACKUP_PATH)
    with open(STORAGE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _fold(s: str) -> str:
    return unicodedata.normalize("NFD", s.strip().lower()).encode("ascii", "ignore").decode()


_VARIANT_FOLDED: dict[str, list[str]] = {
    canonical: [_fold(v) for v in variants]
    for canonical, variants in COLUMN_MAP.items()
}


def normalize_columns(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    normalized: dict[str, str] = {}
    for col in df.columns:
        col_folded = _fold(col)
        for canonical, folded_variants in _VARIANT_FOLDED.items():
            if col_folded in folded_variants or col_folded == canonical:
                normalized[col] = canonical
                break
    df = df.rename(columns=normalized)
    missing = REQUIRED_COLUMNS - set(df.columns)
    return df, list(missing)


def read_csv_with_encoding(raw_bytes: bytes) -> pd.DataFrame:
    for encoding in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            return pd.read_csv(io.BytesIO(raw_bytes), encoding=encoding, dtype=str)
        except UnicodeDecodeError:
            continue
    raise ValueError("Could not decode CSV file. Supported encodings: UTF-8, UTF-8 BOM, Windows-1252.")


def _week_from_date(d: object) -> str | None:
    if d is None or (isinstance(d, float) and pd.isna(d)):
        return None
    iso = d.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def parse_timestamps(df: pd.DataFrame) -> pd.DataFrame:
    if "timestamp" in df.columns:
        parsed_ts = pd.to_datetime(df["timestamp"], dayfirst=True, errors="coerce")
        df["_parsed_ts"] = parsed_ts
    else:
        df["_parsed_ts"] = pd.NaT

    if "date_col" in df.columns:
        parsed_date = pd.to_datetime(df["date_col"], dayfirst=True, errors="coerce")
        if parsed_date.isna().mean() > 0.1:
            parsed_date = pd.to_datetime(df["date_col"], dayfirst=False, errors="coerce")
        df["_date"] = parsed_date.dt.date.astype(str).where(parsed_date.notna(), other=None)
        df["_week"] = parsed_date.dt.date.apply(_week_from_date)
    elif "_parsed_ts" in df.columns:
        df["_date"] = df["_parsed_ts"].dt.date.astype(str).where(df["_parsed_ts"].notna(), other=None)
        df["_week"] = df["_parsed_ts"].dt.date.apply(_week_from_date)
    else:
        raise ValueError("CSV must contain either 'Data (ziua analizată)' or 'Marcaj de timp' column.")

    return df


def str_or_none(val: object) -> str | None:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    s = str(val).strip()
    return s[:MEAL_TEXT_MAX_CHARS] if s else None


def row_to_day(row: pd.Series) -> dict:
    def get(col: str) -> str | None:
        return str_or_none(row.get(col))

    return {
        "date": row.get("_date"),
        "breakfast": get("breakfast"),
        "breakfast_before": get("breakfast_before"),
        "breakfast_after": get("breakfast_after"),
        "lunch": get("lunch"),
        "lunch_before": get("lunch_before"),
        "lunch_after": get("lunch_after"),
        "dinner": get("dinner"),
        "dinner_before": get("dinner_before"),
        "dinner_after": get("dinner_after"),
        "snack": get("snack"),
        "snack_before": get("snack_before"),
        "snack_after": get("snack_after"),
        "transit": get("transit"),
        "exercise": get("exercise"),
        "mindful_eating": get("mindful_eating"),
    }


def compute_summary(days: list[dict]) -> dict:
    def day_has(day: dict, field: str, positive_hints: list[str]) -> bool:
        val = (day.get(field) or "").lower()
        return any(h in val for h in positive_hints)

    return {
        "days_submitted": len(days),
        "exercise_days": sum(
            1 for d in days if day_has(d, "exercise", ["da", "yes", "pași", "pasi", "km", "alerg"])
        ),
        "mindful_eating_days": sum(
            1 for d in days if day_has(d, "mindful_eating", ["da", "yes"])
        ),
        "transit_ok_days": sum(
            1 for d in days if day_has(d, "transit", ["da", "yes", "normal", "bun"])
        ),
        "snack_days": sum(1 for d in days if d.get("snack")),
    }


def parse_csv(raw_bytes: bytes, filename: str) -> tuple[str, list[dict], list[str]]:
    df = read_csv_with_encoding(raw_bytes)
    df, missing = normalize_columns(df)

    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    df = parse_timestamps(df)

    valid_rows = df[df["_week"].notna()].copy()
    if valid_rows.empty:
        raise ValueError("No valid dates found in CSV. Check 'Data (ziua analizată)' or 'Marcaj de timp' column.")

    week_counts = valid_rows["_week"].value_counts()
    week_key: str = week_counts.index[0]

    warnings: list[str] = []

    if "email" not in df.columns:
        raise ValueError("Missing required column: email")

    valid_rows["email"] = valid_rows["email"].str.strip().str.lower()
    valid_rows = valid_rows[valid_rows["email"].notna() & (valid_rows["email"] != "")]

    if "name" in valid_rows.columns:
        valid_rows["name"] = valid_rows["name"].str.strip()

    duplicates = valid_rows[valid_rows.duplicated(subset=["email", "_date"], keep=False)]
    if not duplicates.empty:
        for (email, date), group in duplicates.groupby(["email", "_date"]):
            warnings.append(
                f"Duplicate entry for {email} on {date} — kept latest timestamp."
            )
    valid_rows = valid_rows.sort_values("_parsed_ts").drop_duplicates(
        subset=["email", "_date"], keep="last"
    )

    clients_raw: list[dict] = []
    for email, group in valid_rows.groupby("email"):
        name = group["name"].iloc[-1] if "name" in group.columns else email

        most_recent_date = group["_date"].dropna().max()
        if most_recent_date:
            from datetime import date as date_type, timedelta
            cutoff = (date_type.fromisoformat(most_recent_date) - timedelta(days=6)).isoformat()
            group = group[group["_date"] >= cutoff]
            if group.empty:
                warnings.append(f"Client {email}: no rows within last 7 days — skipped.")
                continue

        days = [row_to_day(row) for _, row in group.iterrows()]
        days_with_data = [
            d for d in days
            if any(d.get(f) for f in ("breakfast", "lunch", "dinner"))
        ]
        if not days_with_data:
            warnings.append(f"Client {email}: all entries are empty — skipped.")
            continue
        if len(days_with_data) < len(days):
            warnings.append(
                f"Client {email}: {len(days) - len(days_with_data)} empty day(s) removed."
            )
        if len(days_with_data) < 7:
            warnings.append(
                f"Client {email}: only {len(days_with_data)} day(s) submitted out of 7."
            )
        clients_raw.append({
            "email": email,
            "name": name,
            "week": week_key,
            "days": days_with_data,
        })

    return week_key, clients_raw, warnings


def _trim_client_weeks(weeks: dict) -> dict:
    if len(weeks) <= MAX_WEEKS_PER_CLIENT:
        return weeks
    sorted_keys = sorted(weeks.keys(), reverse=True)[:MAX_WEEKS_PER_CLIENT]
    return {k: weeks[k] for k in sorted_keys}


def merge_into_storage(
    storage: dict,
    week_key: str,
    clients_raw: list[dict],
    filename: str,
) -> None:
    now = datetime.now(timezone.utc).isoformat()

    for client in clients_raw:
        email = client["email"]
        if email not in storage["clients"]:
            storage["clients"][email] = {
                "name": client["name"],
                "email": email,
                "first_seen": week_key,
                "weeks": {},
            }
        else:
            storage["clients"][email]["name"] = client["name"]

        existing_week = storage["clients"][email]["weeks"].get(week_key, {})
        storage["clients"][email]["weeks"][week_key] = {
            "uploaded_at": now,
            "days": client["days"],
            "feedback": existing_week.get("feedback"),
            "feedback_generated_at": existing_week.get("feedback_generated_at"),
            "summary": compute_summary(client["days"]),
        }
        storage["clients"][email]["weeks"] = _trim_client_weeks(
            storage["clients"][email]["weeks"]
        )

    existing_upload = next(
        (u for u in storage["uploads"] if u.get("week") == week_key), None
    )
    if existing_upload:
        existing_upload.update({
            "uploaded_at": now,
            "clients_count": len(clients_raw),
            "filename": filename,
        })
    else:
        storage["uploads"].append({
            "uploaded_at": now,
            "week": week_key,
            "clients_count": len(clients_raw),
            "filename": filename,
        })

    storage["current_week"] = week_key


@app.post("/debug-columns")
async def debug_columns(file: UploadFile) -> dict:
    try:
        raw_bytes = await file.read()
        df = read_csv_with_encoding(raw_bytes)
        folded = [_fold(c) for c in df.columns]
        return {
            "total_columns": len(df.columns),
            "columns": [
                {"index": i, "raw": col, "folded": folded[i]}
                for i, col in enumerate(df.columns)
            ],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health() -> dict:
    try:
        storage = load_storage()
        return {
            "status": "ok",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "storage": "ok",
            "clients_in_storage": len(storage["clients"]),
            "current_week": storage["current_week"],
            "api_key_loaded": bool(os.getenv("CLAUDE_API_KEY")),
        }
    except RuntimeError as e:
        return {"status": "error", "detail": str(e)}


@app.get("/status")
async def status() -> dict:
    try:
        storage = load_storage()

        total_weeks = sum(
            len(c["weeks"]) for c in storage["clients"].values()
        )

        all_uploads = storage.get("uploads", [])
        last_upload = max((u.get("uploaded_at") for u in all_uploads), default=None)

        all_feedback_dates = [
            wd.get("feedback_generated_at")
            for c in storage["clients"].values()
            for wd in c["weeks"].values()
            if wd.get("feedback_generated_at")
        ]
        last_feedback = max(all_feedback_dates, default=None)

        storage_size_kb = round(STORAGE_PATH.stat().st_size / 1024, 1) if STORAGE_PATH.exists() else 0
        backup_exists = BACKUP_PATH.exists()

        return {
            "storage_size_kb": storage_size_kb,
            "backup_exists": backup_exists,
            "total_clients": len(storage["clients"]),
            "total_weeks_stored": total_weeks,
            "current_week": storage.get("current_week"),
            "last_upload_at": last_upload,
            "last_feedback_at": last_feedback,
            "total_uploads": len(all_uploads),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/upload-csv")
async def upload_csv(file: UploadFile) -> dict:
    try:
        if not file.filename or not file.filename.lower().endswith(".csv"):
            raise HTTPException(status_code=422, detail="File must be a .csv")

        raw_bytes = await file.read()
        week_key, clients_raw, warnings = parse_csv(raw_bytes, file.filename)

        storage = load_storage()
        merge_into_storage(storage, week_key, clients_raw, file.filename)
        save_storage(storage)

        return {
            "week": week_key,
            "clients_found": len(clients_raw),
            "clients": [
                {"email": c["email"], "name": c["name"], "days_submitted": len(c["days"])}
                for c in clients_raw
            ],
            "warnings": warnings,
        }
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {e}")


@app.get("/clients")
async def list_clients(week: str | None = None) -> dict:
    try:
        storage = load_storage()
        target_week = week or storage.get("current_week")

        if not target_week:
            return {"week": None, "clients": [], "message": "No CSV uploaded yet."}

        clients_out: list[dict] = []
        for email, client in storage["clients"].items():
            week_data = client["weeks"].get(target_week)
            if not week_data:
                continue
            all_weeks = sorted(client["weeks"].keys())
            clients_out.append({
                "email": email,
                "name": client["name"],
                "days_submitted": week_data["summary"]["days_submitted"],
                "is_returning": len(all_weeks) > 1,
                "weeks_of_history": len(all_weeks),
                "feedback_generated": week_data.get("feedback") is not None,
            })

        clients_out.sort(key=lambda c: c["name"])
        return {"week": target_week, "clients": clients_out}
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {e}")


SYSTEM_PROMPT = """
You are a nutrition coach assistant generating weekly WhatsApp-style feedback messages for clients.

TONE: Warm, professional, supportive, slightly firm. No diacritics in the output (write Romanian without diacritics: a instead of a/a, i instead of i, s instead of s, t instead of t).

MANDATORY OPENING LINE: Every message must begin with exactly this sentence (replace [first name] with her actual first name):
"Buna, [first name], Sper ca mesajul meu te prinde intr-o stare buna. M-am uitat peste chestionarele tale si as vrea sa iti las un feedback scurt."
This is always the very first line. No exceptions.

STRUCTURE (sandwich — follow this order strictly after the opening):
1. PRAISE: 2-3 specific things she did well this week. Reference real foods and real days. No generic phrases.
   - If she submitted all 7 days: acknowledge this positively in the praise section.
   - If she submitted fewer than 7 days: include this exact sentence naturally within the feedback: "Ar fi de ajutor pentru tine si pentru noi daca ai reusi sa completezi mai des chestionarul."
2. IMPROVEMENTS: 1-2 main things to work on, with 1-2 practical recommendations. Be specific and warm, not clinical.
3. ENCOURAGEMENT: End positively. If emotional eating appears 2+ times, end with an empathetic question instead of advice.

LENGTH: 130-190 words normally. Allow up to 220 if truly needed. Never exceed 220 words.

EVALUATE these areas (only mention what is relevant for this client this week):
- Breakfast: ideally 80% savory, 90% protein-rich (clients are women 37-60, many exercise)
- Protein: present at all main meals
- Vegetables: at least 80% of all main meals
- Meal structure: 3 meals/day ~4 hours apart
- Snacks: only if interval >4h, maximum 4 days out of 7
- Fiber: ~20-30g/day — reference specific foods
- Fat: moderate for fat loss goals
- Movement: 8,000+ steps or equivalent exercise daily
- Bowel movements: daily ideally, minimum every 2 days

SPECIAL CASES:
- Emotional eating frequent (2+ times): end with a warm curious question about what triggered it
- Plant-based/fasting: acknowledge lower protein, suggest plant-based sources (leguminoase, tofu, tempeh, seminte)
- Mindful eating present: congratulate specifically with the number of days
- Mindful eating absent: briefly mention its importance, not preachy
- History available: you MUST include at least one direct week-to-week comparison woven naturally into the text. Use these exact Romanian phrases depending on what you observe:
    * Improvement: "Fata de saptamana trecuta, ai reusit sa..."
    * Unchanged habit (positive or neutral): "A ramas neschimbat faptul ca..."
    * Regression (say warmly, not judgmentally): "Observ ca nu ai mai prioritizat..."
    * Repeating pattern across 2+ weeks: "Este a doua saptamana consecutiva in care..."
    * Comparing to 2 weeks ago: "Comparativ cu acum doua saptamani..."
  Choose whichever phrase fits the actual data. The comparison must feel like natural conversation, not a report. Never mention history if this is the first week.
- First week only: do not reference any history, do not use any of the comparison phrases above

FORMAT RULES:
- Address client by first name
- No bullet points or section headers in the output
- No diacritics (a->a, a->a, i->i, s->s, t->t)
- Flowing paragraphs only
- Every sentence must reference real data from her responses
- No generic filler phrases
""".strip()

ROMANIAN_DAYS = {
    0: "Luni", 1: "Marți", 2: "Miercuri", 3: "Joi",
    4: "Vineri", 5: "Sâmbătă", 6: "Duminică",
}


def build_user_message(client: dict, week_key: str, past_weeks: list[dict]) -> str:
    name = client["name"]
    first_name = name.split()[0] if name else name
    week_data = client["weeks"][week_key]
    days = week_data["days"]

    lines: list[str] = [
        f"Client: {name}",
        f"Săptămâna: {week_key}",
        f"Zile trimise: {len(days)} din 7",
        "",
        "JURNALUL SĂPTĂMÂNII:",
    ]

    for day in sorted(days, key=lambda d: d.get("date") or ""):
        date_str = day.get("date") or "?"
        try:
            from datetime import date as date_type
            d = date_type.fromisoformat(date_str)
            day_label = f"{ROMANIAN_DAYS[d.weekday()]}, {d.strftime('%d %b %Y')}"
        except Exception:
            day_label = date_str

        lines.append(f"\n{day_label}:")
        lines.append(f"  Mic dejun: {day.get('breakfast') or '—'}")
        if day.get("breakfast_before") or day.get("breakfast_after"):
            lines.append(f"  Înainte mic dejun: {day.get('breakfast_before') or '—'} | După: {day.get('breakfast_after') or '—'}")
        lines.append(f"  Prânz: {day.get('lunch') or '—'}")
        if day.get("lunch_before") or day.get("lunch_after"):
            lines.append(f"  Înainte prânz: {day.get('lunch_before') or '—'} | După: {day.get('lunch_after') or '—'}")
        lines.append(f"  Cină: {day.get('dinner') or '—'}")
        if day.get("dinner_before") or day.get("dinner_after"):
            lines.append(f"  Înainte cină: {day.get('dinner_before') or '—'} | După: {day.get('dinner_after') or '—'}")
        if day.get("snack"):
            lines.append(f"  Gustare: {day['snack']}")
            if day.get("snack_before") or day.get("snack_after"):
                lines.append(f"  Înainte gustare: {day.get('snack_before') or '—'} | După: {day.get('snack_after') or '—'}")
        lines.append(f"  Tranzit intestinal: {day.get('transit') or '—'}")
        lines.append(f"  Exerciții: {day.get('exercise') or '—'}")
        lines.append(f"  Mâncat conștient: {day.get('mindful_eating') or '—'}")

    if past_weeks:
        lines.append("\nISTORIC SĂPTĂMÂNI ANTERIOARE:")
        for pw in past_weeks:
            s = pw.get("summary", {})
            lines.append(
                f"\n{pw['week']}: {s.get('days_submitted', '?')} zile trimise | "
                f"Exerciții: {s.get('exercise_days', '?')} zile | "
                f"Mâncat conștient: {s.get('mindful_eating_days', '?')} zile | "
                f"Tranzit ok: {s.get('transit_ok_days', '?')} zile | "
                f"Gustări: {s.get('snack_days', '?')} zile"
            )
            if pw.get("feedback"):
                excerpt = pw["feedback"][:300].rsplit(" ", 1)[0] + "…"
                lines.append(f"  Feedback anterior (extras): {excerpt}")
        lines.append(f"\nNotă: Aceasta este săptămâna {len(past_weeks) + 1} pentru {first_name}. Fă referire explicită la progresul față de săptămânile anterioare.")
    else:
        lines.append(f"\nNotă: Aceasta este prima săptămână pentru {first_name}. Nu există istoric anterior.")

    return "\n".join(lines)


class FeedbackRequest(BaseModel):
    week: str | None = None
    regenerate: bool = False


@app.get("/history/{email}")
async def get_history(email: str, weeks: int = 0) -> dict:
    try:
        storage = load_storage()
        email = email.strip().lower()
        client = storage["clients"].get(email)
        if not client:
            raise HTTPException(status_code=404, detail=f"Client '{email}' not found.")

        all_weeks = sorted(client["weeks"].keys(), reverse=True)
        selected = all_weeks if weeks == 0 else all_weeks[:weeks]

        history = []
        for wk in selected:
            wd = client["weeks"][wk]
            history.append({
                "week": wk,
                "days_submitted": wd["summary"]["days_submitted"],
                "feedback": wd.get("feedback"),
                "feedback_generated_at": wd.get("feedback_generated_at"),
                "summary": wd["summary"],
            })

        return {
            "email": email,
            "name": client["name"],
            "first_seen": client.get("first_seen"),
            "total_weeks": len(all_weeks),
            "history": history,
        }
    except HTTPException:
        raise
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {e}")


@app.post("/feedback/{email}")
async def generate_feedback(email: str, body: FeedbackRequest = FeedbackRequest()) -> dict:
    try:
        storage = load_storage()
        email = email.strip().lower()
        client = storage["clients"].get(email)
        if not client:
            raise HTTPException(status_code=404, detail=f"Client '{email}' not found.")

        week_key = body.week or storage.get("current_week")
        if not week_key:
            raise HTTPException(status_code=422, detail="No week specified and no CSV uploaded yet.")

        week_data = client["weeks"].get(week_key)
        if not week_data:
            raise HTTPException(status_code=404, detail=f"No data for '{email}' in week {week_key}.")

        if week_data.get("feedback") and not body.regenerate:
            return {
                "email": email,
                "name": client["name"],
                "week": week_key,
                "feedback": week_data["feedback"],
                "generated_at": week_data.get("feedback_generated_at"),
                "days_analyzed": week_data["summary"]["days_submitted"],
                "from_cache": True,
            }

        all_weeks = sorted(client["weeks"].keys(), reverse=True)
        past_weeks = [
            {"week": wk, **client["weeks"][wk]}
            for wk in all_weeks
            if wk != week_key and client["weeks"][wk].get("feedback")
        ][:3]

        user_message = build_user_message(client, week_key, past_weeks)

        api_key = os.getenv("CLAUDE_API_KEY")
        if not api_key:
            raise HTTPException(status_code=500, detail="CLAUDE_API_KEY not set.")

        claude = anthropic.Anthropic(api_key=api_key)
        response = None
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                response = claude.messages.create(
                    model="claude-opus-4-6",
                    max_tokens=1024,
                    temperature=1,
                    system=SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": user_message}],
                )
                break
            except anthropic.RateLimitError as e:
                raise HTTPException(status_code=503, detail="Claude API rate limit reached. Please wait 60 seconds and try again.")
            except (anthropic.APIStatusError, anthropic.APIConnectionError) as e:
                last_error = e
                if attempt == 0:
                    logging.warning("Claude API transient error (%s) — retrying in 3s.", e)
                    time.sleep(3)
        if response is None:
            raise HTTPException(status_code=503, detail=f"Claude API unavailable after retry: {last_error}")

        feedback_text = response.content[0].text
        now = datetime.now(timezone.utc).isoformat()

        storage["clients"][email]["weeks"][week_key]["feedback"] = feedback_text
        storage["clients"][email]["weeks"][week_key]["feedback_generated_at"] = now
        save_storage(storage)

        return {
            "email": email,
            "name": client["name"],
            "week": week_key,
            "feedback": feedback_text,
            "generated_at": now,
            "days_analyzed": week_data["summary"]["days_submitted"],
            "from_cache": False,
        }
    except HTTPException:
        raise
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {e}")
