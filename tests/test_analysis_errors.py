from rainclass.ai import AnalysisError
from rainclass.analysis_errors import public_error

def test_budget_network_and_schema_are_distinct():
    assert '预算' in public_error(AnalysisError('单课预算或调用上限已达到'))
    assert '预算' in public_error(AnalysisError('Course budget/call limit reached'))
    assert '网络' in public_error(AnalysisError('Network/timeout/invalid response; outcome unknown; not retried'))
    assert '数量' in public_error(AnalysisError('Blank count mismatch'))

def test_unknown_error_never_displays_arbitrary_details():
    secret='https://private.example/?key=SECRET'
    assert secret not in public_error(AnalysisError(secret))
    assert secret not in public_error(RuntimeError(secret))
