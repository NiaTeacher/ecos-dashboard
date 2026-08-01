import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests


API_KEY = os.environ.get("ECOS_API_KEY", "").strip()

if not API_KEY:
    raise RuntimeError("ECOS_API_KEY가 설정되지 않았습니다.")


KST = timezone(timedelta(hours=9))


INDICATORS = [
    {
        "category": "금리",
        "name": "한국은행 기준금리",
        "stat_code": "722Y001",
        "cycle": "D",
        "item_code": "0101000",
        "default_unit": "%",
    },
    {
        "category": "환율",
        "name": "원/달러 환율",
        "stat_code": "731Y001",
        "cycle": "D",
        "item_code": "0000001",
        "default_unit": "원",
    },
    {
        "category": "채권",
        "name": "국고채 3년",
        "stat_code": "817Y002",
        "cycle": "D",
        "item_code": "010200000",
        "default_unit": "%",
    },
    {
        "category": "채권",
        "name": "국고채 10년",
        "stat_code": "817Y002",
        "cycle": "D",
        "item_code": "010210000",
        "default_unit": "%",
    },
]


def make_ecos_url(
    stat_code: str,
    cycle: str,
    start_date: str,
    end_date: str,
    item_code: str,
) -> str:
    parts = [
        "https://ecos.bok.or.kr/api/StatisticSearch",
        quote(API_KEY, safe=""),
        "json",
        "kr",
        "1",
        "1000",
        quote(stat_code, safe=""),
        quote(cycle, safe=""),
        quote(start_date, safe=""),
        quote(end_date, safe=""),
        quote(item_code, safe=""),
    ]

    return "/".join(parts)


def fetch_indicator(indicator: dict[str, str]) -> dict[str, Any]:
    today = datetime.now(KST).date()

    # 최근 1년
    start_date = (today - timedelta(days=365)).strftime("%Y%m%d")
    end_date = today.strftime("%Y%m%d")

    url = make_ecos_url(
        stat_code=indicator["stat_code"],
        cycle=indicator["cycle"],
        start_date=start_date,
        end_date=end_date,
        item_code=indicator["item_code"],
    )

    response = requests.get(
        url,
        timeout=30,
        headers={
            "Accept": "application/json",
            "User-Agent": "ecos-dashboard/1.0",
        },
    )

    response.raise_for_status()

    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError(
            f"ECOS 응답이 JSON이 아닙니다: {response.text[:200]}"
        ) from exc

    if "RESULT" in data:
        result = data["RESULT"]

        raise RuntimeError(
            f'{result.get("CODE", "UNKNOWN")}: '
            f'{result.get("MESSAGE", "ECOS 오류")}'
        )

    rows = data.get("StatisticSearch", {}).get("row", [])

    history: list[dict[str, Any]] = []

    for row in rows:
        raw_value = row.get("DATA_VALUE")

        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            continue

        history.append(
            {
                "date": str(row.get("TIME", "")),
                "value": value,
            }
        )

    if not history:
        raise RuntimeError("유효한 숫자 데이터가 없습니다.")

    # 날짜 오름차순
    history.sort(key=lambda item: item["date"])

    current = history[-1]
    previous = history[-2] if len(history) >= 2 else None

    previous_value = (
        previous["value"]
        if previous is not None
        else None
    )

    change = (
        current["value"] - previous_value
        if previous_value is not None
        else None
    )

    change_rate = (
        change / previous_value
        if previous_value not in (None, 0)
        else None
    )

    return {
        "category": indicator["category"],
        "name": indicator["name"],
        "current_value": current["value"],
        "previous_value": previous_value,
        "change": change,
        "change_rate": change_rate,
        "date": current["date"],
        "unit": indicator["default_unit"],
        "stat_code": indicator["stat_code"],
        "item_code": indicator["item_code"],
        "status": "success",
        "error": "",
        "history": history,
    }


def main() -> None:
    results: list[dict[str, Any]] = []

    for indicator in INDICATORS:
        try:
            result = fetch_indicator(indicator)
            results.append(result)

            print(
                f'[성공] {indicator["name"]}: '
                f'{result["current_value"]} '
                f'({len(result["history"])}건)'
            )

        except Exception as exc:
            print(
                f'[실패] {indicator["name"]}: {exc}',
                file=sys.stderr,
            )

            results.append(
                {
                    "category": indicator["category"],
                    "name": indicator["name"],
                    "current_value": None,
                    "previous_value": None,
                    "change": None,
                    "change_rate": None,
                    "date": "",
                    "unit": indicator["default_unit"],
                    "stat_code": indicator["stat_code"],
                    "item_code": indicator["item_code"],
                    "status": "error",
                    "error": str(exc),
                    "history": [],
                }
            )

    output = {
        "updated_at": datetime.now(KST).isoformat(
            timespec="seconds"
        ),
        "timezone": "Asia/Seoul",
        "source": "한국은행 ECOS",
        "indicators": results,
    }

    Path("ecos_data.json").write_text(
        json.dumps(
            output,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print("ecos_data.json 저장 완료")


if __name__ == "__main__":
    main()
