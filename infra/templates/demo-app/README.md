# Local harmless demo app

This fixed-version Python HTTP service is used to check that an isolated Compose
environment can start, connect between containers, and return one expected
benign response. It only answers `GET /health` and `GET /demo`; it contains no
vulnerability or exploit behavior.
