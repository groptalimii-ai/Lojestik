"""
Run with: pytest tests/ (from /backend, with PYTHONPATH set to backend/)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.services.lead_extraction import classify_intake_text


def test_carrier_examples_classify_as_carrier():
    """These are literally the operator's own example messages -- pins the
    classification rule against real input, not synthetic cases."""
    assert classify_intake_text("ابو سعد سطحه من الدمام للرياض رقم التواصل 0500000000") == "carrier"
    assert classify_intake_text("محمد شاحنه ثلاجه من عسير إلى الطايف رقم التواصل 0500000000") == "carrier"
    assert classify_intake_text("سعد تريلا من عرعر إلى تبوك رقم التواصل 0500000000") == "carrier"


def test_load_examples_classify_as_load():
    assert classify_intake_text("خالد حمولة 29 طن من الرياض ل جده السعر 3000 رقم التواصل 0500000000") == "load"
    assert classify_intake_text("عندي 15 طن اسمنت من مكة للمدينة") == "load"


def test_classifier_is_keyword_based_not_ai():
    """A message with neither keyword defaults to carrier -- documents the
    actual rule (not a smarter guess) so a future change here is a
    deliberate decision, not a silent regression."""
    assert classify_intake_text("سيارة صغيرة من جدة للطائف") == "carrier"
