ARG BASE_IMAGE=docker.io/library/debian:trixie-slim
FROM ${BASE_IMAGE}

LABEL org.cachyos.builder.version="2"

ENV DEBIAN_FRONTEND=noninteractive \
    HOME=/tmp

RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    build-essential \
    bc \
    bison \
    flex \
    gawk \
    perl \
    file \
    pkgconf \
    libssl-dev \
    libelf-dev \
    libncurses-dev \
    libdw-dev \
    libudev-dev \
    libpci-dev \
    libiberty-dev \
    libyaml-dev \
    libcap-dev \
    libnuma-dev \
    autoconf \
    dwarves \
    pahole \
    zstd \
    xz-utils \
    bzip2 \
    gzip \
    tar \
    lz4 \
    cpio \
    rsync \
    kmod \
    fakeroot \
    dpkg-dev \
    debhelper \
    devscripts \
    git \
    curl \
    wget \
    ca-certificates \
    python3 \
    python3-gi \
    python3-requests \
    python3-packaging \
    clang \
    llvm \
    lld \
    sbsigntool \
    mokutil \
    openssl \
    linux-base \
    initramfs-tools \
    && rm -rf /var/lib/apt/lists/*

ENV DEBFULLNAME="CachyOS Debian Builder"
ENV DEBEMAIL="builder@localhost"

WORKDIR /workspace
