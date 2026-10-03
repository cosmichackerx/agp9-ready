# Contributing

    python -m venv .venv && . .venv/bin/activate
    pip install -e . pytest
    pytest -q

* A new rule needs an entry in `src/agp9_ready/rules.py` with the Android Developers section it comes from, a detector in `scan.py`, and unit tests with positive and negative cases.
* Rules are checked against a real Android Gradle Plugin. Add the construct as a case in `tests/oracle/run_oracle.py` and run it (`python tests/oracle/run_oracle.py --gradle /path/to/gradle-9.x/bin/gradle`; needs `ANDROID_HOME` and JDK 17+). If AGP does not fail or warn on it, say so in the rule (`oracle=False`) and in the README.
* Fixes (`--fix`) must be safe: add the case to `tests/test_rules.py`.
* Keep the project dependency-free (standard library only) and compatible with Python 3.9.
