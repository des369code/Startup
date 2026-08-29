# tests/test_models.py
from takeoff.models import CandidateRegion, Measurement

def test_measurement_requires_world_quantity():
    m = Measurement(
        class_id="C1", class_name_en="Asphalt", measure="area",
        quantity=25.0, unit="m2", source_ids=["R1"], confidence=1.0,
    )
    assert m.quantity == 25.0
    assert m.unit == "m2"
