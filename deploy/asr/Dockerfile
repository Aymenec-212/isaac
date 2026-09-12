# Build only on linux/amd64; no GPU needed at build time with explicit T4 compute capability.
FROM rust:1.89.0-bookworm@sha256:948f9b08a66e7fe01b03a98ef1c7568292e07ec2e4fe90d88c07bb14563c84ff AS rust
FROM nvidia/cuda:12.8.1-devel-ubuntu24.04@sha256:520292dbb4f755fd360766059e62956e9379485d9e073bbd2f6e3c20c270ed66 AS build
COPY --from=rust /usr/local/rustup /usr/local/rustup
COPY --from=rust /usr/local/cargo /usr/local/cargo
ENV RUSTUP_HOME=/usr/local/rustup CARGO_HOME=/usr/local/cargo PATH=/usr/local/cargo/bin:$PATH CUDA_COMPUTE_CAP=75
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates build-essential cmake pkg-config libssl-dev libopus-dev python3-dev && rm -rf /var/lib/apt/lists/*
WORKDIR /src
RUN git init && git remote add origin https://github.com/kyutai-labs/moshi.git && git fetch --depth 1 origin e6a55d2722a65870ef52a6c9f6ecfc0e90f38362 && git checkout --detach FETCH_HEAD
WORKDIR /src/rust
RUN cargo build --locked --release --package moshi-server --features cuda
FROM nvidia/cuda:12.8.1-runtime-ubuntu24.04@sha256:ebef3c171eeef0298e4eb2e4be843105edf3b8b0ac45e0b43acee358e8046867
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates libssl3t64 libopus0 libpython3.12 python3 && rm -rf /var/lib/apt/lists/*
COPY --from=build /src/rust/target/release/moshi-server /usr/local/bin/moshi-server
COPY entrypoint.py config.toml /opt/mosaique/
RUN mkdir -p /opt/mosaique/static
USER 10001:10001
ENTRYPOINT ["python3", "/opt/mosaique/entrypoint.py"]
