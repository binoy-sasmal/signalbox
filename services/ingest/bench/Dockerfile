# Decode benchmark only. NOT the runtime image -- building and pushing a
# multi-arch runtime image is Gate 6, and nothing here is a step toward it.
#
# This exists because PLAN.md section 7 requires the decode benchmark to run
# inside a Linux container so that architecture is the only remaining confound
# between the measurement and the pod.
#
# Pinned by digest, per CLAUDE.md.
FROM python:3.12-slim@sha256:09f7da3bc104798d0afb40bc08d23ab2da20a76130cec1f2ef170848f5d85217

# Same pinned versions as the service, so the decode path being measured is the
# decode path that runs.
RUN pip install --no-cache-dir \
      gtfs-realtime-bindings==2.2.0 \
      protobuf==7.36.0

WORKDIR /bench
COPY decode_bench.py /bench/decode_bench.py
ENTRYPOINT ["python", "/bench/decode_bench.py"]
