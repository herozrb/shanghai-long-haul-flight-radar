from __future__ import annotations

import json
import hashlib
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent
PAGE_PATH = ROOT / "index.html"
TRACKING_ROOT = ROOT / ".tracking"
FLYCLAW_PATH = Path("/Users/zhourongbing/.agents/skills/flyclaw/flyclaw.py")
DEPARTURE_DATE = "2026-09-25"
RETURN_DATE = "2026-10-07"
MAX_DURATION_MINUTES = 20 * 60
MAX_WORKERS = 2
QUERY_TIMEOUT_SECONDS = 35

DESTINATIONS = {
    "卡萨布兰卡": "非洲",
    "巴塞罗那": "欧洲",
    "埃里温": "亚洲",
    "赫尔辛基": "欧洲",
    "奥克兰": "大洋洲",
    "亚的斯亚贝巴": "非洲",
    "马德里": "欧洲",
    "旧金山": "北美",
    "墨尔本": "大洋洲",
    "珀斯": "大洋洲",
    "巴黎": "欧洲",
    "第比利斯": "亚洲",
    "阿姆斯特丹": "欧洲",
    "布达佩斯": "欧洲",
    "伦敦": "欧洲",
    "慕尼黑": "欧洲",
    "温哥华": "北美",
    "约翰内斯堡": "非洲",
    "维也纳": "欧洲",
    "加德满都": "亚洲",
    "洛杉矶": "北美",
    "伊斯坦布尔": "亚洲",
    "内罗毕": "非洲",
    "哥本哈根": "欧洲",
    "圣保罗": "南美",
    "基督城": "大洋洲",
    "墨西哥城": "北美",
    "多伦多": "北美",
    "布拉格": "欧洲",
    "布里斯班": "大洋洲",
    "开普敦": "非洲",
    "开罗": "非洲",
    "悉尼": "大洋洲",
    "波士顿": "北美",
    "纽约": "北美",
    "罗马": "欧洲",
    "芝加哥": "北美",
    "苏黎世": "欧洲",
    "西雅图": "北美",
    "里斯本": "欧洲",
    "阿德莱德": "大洋洲",
    "雅典": "欧洲",
    "马斯喀特": "亚洲",
}

AIRPORT_NAMES = {
    "ADD": "亚的斯亚贝巴",
    "BKK": "曼谷",
    "BNE": "布里斯班",
    "CAN": "广州",
    "CDG": "巴黎",
    "CKG": "重庆",
    "CTU": "成都",
    "DOH": "多哈",
    "DXB": "迪拜",
    "HEL": "赫尔辛基",
    "HKG": "香港",
    "ICN": "首尔",
    "IST": "伊斯坦布尔",
    "KUL": "吉隆坡",
    "LHR": "伦敦",
    "NRT": "东京",
    "PEK": "北京",
    "PKX": "北京",
    "SIN": "新加坡",
    "SZX": "深圳",
    "TFU": "成都",
    "TPE": "台北",
    "URC": "乌鲁木齐",
    "VIE": "维也纳",
    "WNZ": "温州",
    "XMN": "厦门",
}


def read_current_data(page_text: str) -> tuple[list[dict], list[str]]:
    flights_match = re.search(r"const flights=(.*?);\s*const unavailable=", page_text, re.S)
    unavailable_match = re.search(r"const unavailable=(.*?);\s*const updatedAt=", page_text, re.S)
    if not flights_match or not unavailable_match:
        raise RuntimeError("Unable to locate current flight data")
    script = (
        f"const flights={flights_match.group(1)};"
        f"const unavailable={unavailable_match.group(1)};"
        "process.stdout.write(JSON.stringify({flights,unavailable}));"
    )
    process = subprocess.run(
        ["node"], input=script, text=True, capture_output=True, timeout=10, check=False
    )
    if process.returncode != 0:
        raise RuntimeError(process.stderr.strip() or "Unable to parse current flight data")
    data = json.loads(process.stdout)
    return data["flights"], data["unavailable"]


def parse_json_output(output: str) -> list[dict]:
    start = output.find("[")
    end = output.rfind("]")
    if start < 0 or end < start:
        raise ValueError("No JSON array in query output")
    data = json.loads(output[start : end + 1])
    if not isinstance(data, list):
        raise ValueError("Query output is not a list")
    return data


def query_destination(destination: str, run_dir: Path) -> dict:
    command = [
        sys.executable,
        str(FLYCLAW_PATH),
        "search",
        "--from",
        "上海",
        "--to",
        destination,
        "--date",
        DEPARTURE_DATE,
        "--return",
        RETURN_DATE,
        "--adults",
        "1",
        "--cabin",
        "economy",
        "--stops",
        "any",
        "--sort",
        "cheapest",
        "--currency",
        "cny",
        "--limit",
        "20",
    ]
    last_result: dict | None = None
    for attempt in range(2):
        try:
            process = subprocess.run(
                command,
                text=True,
                capture_output=True,
                timeout=QUERY_TIMEOUT_SECONDS,
                check=False,
            )
            result = {
                "destination": destination,
                "attempt": attempt + 1,
                "returncode": process.returncode,
                "stdout": process.stdout,
                "stderr": process.stderr,
            }
            last_result = result
            if process.returncode == 0:
                try:
                    result["records"] = parse_json_output(process.stdout)
                    source_errors = [
                        marker
                        for marker in (
                            "Fliggy MCP query failed",
                            "Skiplagged returned HTTP",
                            "Google Flights query failed",
                            "Google Flights search failed",
                        )
                        if marker in process.stderr
                    ]
                    if not result["records"] and source_errors:
                        result["status"] = "source_error"
                        result["error"] = "No records with upstream errors: " + ", ".join(source_errors)
                    else:
                        result["status"] = "success"
                        break
                except (json.JSONDecodeError, ValueError) as error:
                    result["status"] = "parse_error"
                    result["error"] = str(error)
            else:
                result["status"] = "query_error"
                result["error"] = f"Exit code {process.returncode}"
        except subprocess.TimeoutExpired as error:
            last_result = {
                "destination": destination,
                "attempt": attempt + 1,
                "status": "query_error",
                "error": f"Timeout after {QUERY_TIMEOUT_SECONDS} seconds",
                "stdout": error.stdout or "",
                "stderr": error.stderr or "",
            }
        if attempt == 0:
            time.sleep(3)
    if last_result is None:
        raise RuntimeError("Query did not produce a result")
    safe_name = hashlib.sha1(destination.encode("utf-8")).hexdigest()[:12]
    (run_dir / f"{safe_name}.json").write_text(
        json.dumps(last_result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return last_result


def itinerary_key(record: dict) -> tuple:
    outbound_stops = record.get("stops")
    inbound_stops = record.get("return_stops")
    outbound_duration = record.get("duration_minutes")
    inbound_duration = record.get("return_duration_minutes")
    price = record.get("price")
    both_direct = outbound_stops == 0 and inbound_stops == 0
    return (
        0 if both_direct else 1,
        int(outbound_stops) + int(inbound_stops),
        float(price),
        int(outbound_duration) + int(inbound_duration),
    )


def qualifying_records(records: list[dict]) -> list[dict]:
    qualified = []
    for record in records:
        required = [
            record.get("price"),
            record.get("currency"),
            record.get("stops"),
            record.get("return_stops"),
            record.get("duration_minutes"),
            record.get("return_duration_minutes"),
        ]
        if any(value is None for value in required):
            continue
        if str(record["currency"]).upper() != "CNY" or float(record["price"]) <= 0:
            continue
        if int(record["duration_minutes"]) > MAX_DURATION_MINUTES:
            continue
        if int(record["return_duration_minutes"]) > MAX_DURATION_MINUTES:
            continue
        qualified.append(record)
    return sorted(qualified, key=itinerary_key)


def format_duration(minutes: int) -> str:
    hours, remainder = divmod(int(minutes), 60)
    return f"{hours}h{remainder:02d}"


def unique(values: list[str]) -> list[str]:
    output = []
    for value in values:
        if value and value not in output:
            output.append(value)
    return output


def flight_numbers(record: dict) -> str:
    segments = list(record.get("segments") or []) + list(record.get("return_segments") or [])
    numbers = unique([str(segment.get("flight_number") or "") for segment in segments])
    if not numbers:
        numbers = unique(
            [str(record.get("flight_number") or ""), str(record.get("return_flight_number") or "")]
        )
    return " / ".join(numbers)


def transit_text(record: dict) -> str:
    outbound_stops = int(record["stops"])
    inbound_stops = int(record["return_stops"])
    outbound_codes = record.get("layover_cities") or []
    inbound_codes = record.get("return_layover_cities") or []
    outbound_names = " / ".join(AIRPORT_NAMES.get(code, code) for code in outbound_codes)
    inbound_names = " / ".join(AIRPORT_NAMES.get(code, code) for code in inbound_codes)
    if outbound_stops == 0 and inbound_stops == 0:
        return "往返直飞"
    outbound_text = "直飞" if outbound_stops == 0 else f"{outbound_names or '中途'}转机"
    inbound_text = "直飞" if inbound_stops == 0 else f"{inbound_names or '中途'}转机"
    return f"去程{outbound_text}，返程{inbound_text}"


def build_flight(destination: str, record: dict, previous_price: int | None) -> dict:
    airlines = unique(
        [str(record.get("airline") or ""), str(record.get("return_airline") or "")]
    )
    flight = {
        "destination": destination,
        "region": DESTINATIONS[destination],
        "price": int(round(float(record["price"]))),
        "outbound": format_duration(record["duration_minutes"]),
        "inbound": format_duration(record["return_duration_minutes"]),
        "transfer": transit_text(record),
        "airlines": "、".join(airlines),
        "numbers": flight_numbers(record),
        "nonstop": int(record["stops"]) == 0 and int(record["return_stops"]) == 0,
    }
    if previous_price is not None:
        flight["previousPrice"] = previous_price
    return flight


def validate_page(page_text: str) -> None:
    script_matches = re.findall(r"<script>(.*?)</script>", page_text, re.S)
    if len(script_matches) != 1:
        raise RuntimeError("Expected one inline script")
    process = subprocess.run(
        ["node", "--check"],
        input=script_matches[0],
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    if process.returncode != 0:
        raise RuntimeError(process.stderr.strip() or "Inline script syntax check failed")
    if "较上次" not in page_text or "updatedAt" not in page_text:
        raise RuntimeError("Tracking display is missing")


def update_page(page_text: str, flights: list[dict], unavailable: list[str], updated_at: str) -> str:
    data_block = (
        "const flights="
        + json.dumps(flights, ensure_ascii=False, separators=(",", ":"))
        + ";\n    const unavailable="
        + json.dumps(unavailable, ensure_ascii=False, separators=(",", ":"))
        + ";"
    )
    updated = re.sub(
        r"const flights=.*?;\s*const unavailable=.*?;",
        data_block,
        page_text,
        count=1,
        flags=re.S,
    )
    updated = re.sub(
        r'const updatedAt="[^"]+";',
        f'const updatedAt="{updated_at}";',
        updated,
        count=1,
    )
    validate_page(updated)
    return updated


def main() -> int:
    page_text = PAGE_PATH.read_text(encoding="utf-8")
    current_flights, current_unavailable = read_current_data(page_text)
    current_by_destination = {flight["destination"]: flight for flight in current_flights}
    run_time = datetime.now(ZoneInfo("Asia/Shanghai"))
    run_id = run_time.strftime("%Y%m%d-%H%M%S")
    run_dir = TRACKING_ROOT / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    results = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(query_destination, destination, run_dir): destination
            for destination in DESTINATIONS
        }
        for future in as_completed(futures):
            destination = futures[future]
            try:
                results[destination] = future.result()
            except Exception as error:
                results[destination] = {
                    "destination": destination,
                    "status": "query_error",
                    "error": str(error),
                }

    updated_flights = []
    updated_unavailable = []
    report = {
        "updatedAt": run_time.strftime("%Y-%m-%d %H:%M"),
        "success": 0,
        "sourceError": 0,
        "queryError": 0,
        "parseError": 0,
        "noResult": 0,
        "changes": [],
        "newlyQualified": [],
        "newlyUnavailable": [],
        "preserved": [],
    }

    for destination in DESTINATIONS:
        result = results[destination]
        status = result.get("status")
        previous = current_by_destination.get(destination)
        if status != "success":
            if status == "parse_error":
                report["parseError"] += 1
            elif status == "source_error":
                report["sourceError"] += 1
            else:
                report["queryError"] += 1
            report["preserved"].append(destination)
            if previous:
                preserved = dict(previous)
                preserved["stale"] = True
                updated_flights.append(preserved)
            else:
                updated_unavailable.append(destination)
            continue

        report["success"] += 1
        qualified = qualifying_records(result.get("records") or [])
        if not qualified:
            report["noResult"] += 1
            updated_unavailable.append(destination)
            if previous:
                report["newlyUnavailable"].append(destination)
            continue

        previous_price = int(previous["price"]) if previous else None
        flight = build_flight(destination, qualified[0], previous_price)
        updated_flights.append(flight)
        if previous_price is None:
            report["newlyQualified"].append(destination)
        else:
            difference = flight["price"] - previous_price
            if difference:
                report["changes"].append(
                    {
                        "destination": destination,
                        "previousPrice": previous_price,
                        "price": flight["price"],
                        "difference": difference,
                    }
                )

    updated_flights.sort(key=lambda flight: flight["price"], reverse=True)
    updated_unavailable = [destination for destination in DESTINATIONS if destination in updated_unavailable]
    updated_page = update_page(page_text, updated_flights, updated_unavailable, report["updatedAt"])
    PAGE_PATH.write_text(updated_page, encoding="utf-8")

    report["qualified"] = len(updated_flights)
    report["unavailable"] = len(updated_unavailable)
    report["currentPreferred"] = min(
        (flight for flight in updated_flights if flight["nonstop"]),
        key=lambda flight: flight["price"],
        default=min(updated_flights, key=lambda flight: flight["price"], default=None),
    )
    (run_dir / "summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (TRACKING_ROOT / "latest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
