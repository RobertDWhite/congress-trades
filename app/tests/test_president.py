from ingest import normalize as nz
from ingest import president as pres

# Representative OGE Form 278-T text (pdftotext -layout output), reproducing the OCR noise
# seen in real filings: $->s/S and bullet separators in amounts, a dropped date slash
# ("8/112025"), garbled "purchase" spellings, bond maturity dates inside the description,
# the form's repeated name line, and a description wrapped across two lines.
SAMPLE = """OGE Form 278-T (Updated February 2024)
#              Description                                          Type Date            Notification          Amount
Filer's Name
Donald J Trump
                KANSAS CITY MO WTR REV SER A B/E 3.25 % Due Dec 1, 2034        ourchaso    9/3/2025     No     $1,001 - $15,000
                BLACK BELT ENERGY GAS DIST AL GAS REV PJ 4.00 % Due Oct 1, 2052   ourchaso    8/28/2025    Yes    $250,001 • $500,000
                KENTUCKY KY PUB ENERGY AUTH 4.00 % Due Dec 1, 2050    nurchasc   8/112025     No     $50,001 • $100,000
                INTEL CORP 3.75% DUE 08/05/27          ourchase    8/29/2025    Yes    s1,000,001 - S5,000,000
                APPLE INC COM             sold        7/15/2025    No     $15,001 - $50,000
                BROWARD CNTY FL 2.384% AIR TRAN DUE 10/01/26
                XTRO TAXBL            ourchaso    8/29/2025    Yes    $1,000,001 - $5,000,000"""


def _rows():
    return pres.parse_278t(SAMPLE, filer_name="Donald J. Trump")


def test_parses_all_transaction_rows_skips_headers_and_name():
    rows = _rows()
    assert len(rows) == 6  # 6 transactions; form headers and the name line are skipped
    assert all("trump" not in r["asset_name"].lower() for r in rows)


def test_amount_brackets_tolerate_ocr_dollars_and_bullets():
    rows = _rows()
    assert (rows[0]["amount_min"], rows[0]["amount_max"]) == (1001, 15000)
    assert (rows[1]["amount_min"], rows[1]["amount_max"]) == (250001, 500000)  # bullet sep
    assert (rows[3]["amount_min"], rows[3]["amount_max"]) == (1000001, 5000000)  # s/S dollars


def test_transaction_date_anchors_on_filing_period_not_maturity():
    rows = _rows()
    # the 08/05/27 maturity in the description must not be taken as the transaction date
    assert rows[3]["transaction_date"] == "2025-08-29"
    # a dropped date slash ("8/112025") is healed
    assert rows[2]["transaction_date"] == "2025-08-11"


def test_transaction_type_classification():
    rows = _rows()
    assert [r["transaction_type"] for r in rows[:4]] == ["purchase"] * 4
    assert rows[4]["transaction_type"] == "sale"


def test_description_preserved_and_wrapped_lines_joined():
    rows = _rows()
    assert "3.75" in rows[3]["asset_name"]  # coupon decimal not corrupted by date healing
    assert "BROWARD" in rows[5]["asset_name"] and "XTRO" in rows[5]["asset_name"]


def test_dedup_key_disambiguates_null_ticker_by_asset_name():
    # The President's bond purchases share date/amount/type with no ticker; the asset name
    # must keep them as distinct trades instead of collapsing onto one dedup_key.
    a = nz.dedup_key("executive", "donald trump", "2025-08-28", None, 1000001, 5000000,
                     "purchase", asset_name="BLACK BELT ENERGY")
    b = nz.dedup_key("executive", "donald trump", "2025-08-28", None, 1000001, 5000000,
                     "purchase", asset_name="INTEL CORP")
    assert a != b


def test_dedup_key_ignores_asset_name_when_ticker_present():
    # Back-compat: ticker-bearing trades (all congressional history) are keyed exactly as
    # before, regardless of asset name.
    base = nz.dedup_key("house", "jane doe", "2026-01-02", "NVDA", 1000, 15000, "purchase")
    with_a = nz.dedup_key("house", "jane doe", "2026-01-02", "NVDA", 1000, 15000,
                          "purchase", asset_name="X")
    with_b = nz.dedup_key("house", "jane doe", "2026-01-02", "NVDA", 1000, 15000,
                          "purchase", asset_name="Y")
    assert base == with_a == with_b
