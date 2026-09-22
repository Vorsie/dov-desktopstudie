#!/bin/sh
# Run the shell test suite in the QGIS containers, exactly the way ci-qgis.yml does.
#
# The shell tests only run in a Python that has qgis, and the two images are the oldest version
# the plugin claims (3.34) and the newest, which is where a 4.x API break shows up first. Three
# things go wrong only in there - the sip enum types on 3.34, the percent-encoded provider URIs on
# 4.x, and the deprecated messageReceived signal - so "green on this laptop" is not an answer.
#
#   scripts/ci_containers.sh                      # both images
#   scripts/ci_containers.sh qgis/qgis:latest     # one of them
#
# Needs Docker and the images pulled once (docker pull qgis/qgis:release-3_34). On Windows run it
# from Git Bash: MSYS_NO_PATHCONV and `pwd -W` are what keep the bind mount a Windows path.
#
# Keep in step with .github/workflows/ci-qgis.yml - tests/scripts/test_ci_containers.py fails when
# the images or the pytest arguments here and there drift apart.
set -e

IMAGES="qgis/qgis:release-3_34 qgis/qgis:latest"
# The live pipeline test is deselected by name as well as by marker: it takes a quarter of an hour
# against the real DOV services.
PYTEST_ARGS='tests/qgis -q -m "not live" --deselect tests/qgis/test_pipeline.py::test_live_pipeline_for_gent'
# Not in the workflow: the container runs as root in a mounted checkout, and a .pytest_cache
# written there is owned by root afterwards.
LOCAL_ARGS="-p no:cacheprovider"

cd "$(dirname "$0")/.."
ROOT="$(pwd -W 2>/dev/null || pwd)"
status=0

for image in ${1:-$IMAGES}; do
    echo "=== $image ==="
    # The images ship a system Python that pip refuses to write into without the flag (PEP 668);
    # the older image predates that refusal and does not know the flag.
    MSYS_NO_PATHCONV=1 docker run --rm -v "$ROOT":/src -w /src \
        -e QT_QPA_PLATFORM=offscreen -e QT_QPA_FONTDIR=/usr/share/fonts \
        "$image" sh -c "
            python3 -m pip install --break-system-packages -q pytest 2>/dev/null \
                || python3 -m pip install -q pytest
            python3 -m pytest $PYTEST_ARGS $LOCAL_ARGS
        " || status=1
done

exit $status
