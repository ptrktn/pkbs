#!/bin/sh
# Original source: https://get.k3s.io

set -e
set -o noglob

# Usage:
#   curl ... | ENV_VAR=... sh -
#       or
#   ENV_VAR=... ./install.sh
#
# Example:
#   Installing a server without traefik:
#     curl ... | INSTALL_K3S_EXEC="--disable=traefik" sh -
#   Installing an agent to point at a server: FIXME
#     curl ... | K3S_TOKEN=xxx K3S_URL=https://server-url:6443 sh -
#

DOWNLOADER=

# --- helper functions for logs ---
info()
{
    echo '[INFO] ' "$@"
}
warn()
{
    echo '[WARN] ' "$@" >&2
}
fatal()
{
    echo '[ERROR] ' "$@" >&2
    exit 1
}

# --- system checks ---
verify_system() {
	/bin/true
}

# --- add quotes to command arguments ---
quote() {
    for arg in "$@"; do
        printf '%s\n' "$arg" | sed "s/'/'\\\\''/g;1s/^/'/;\$s/\$/'/"
    done
}

# --- add indentation and trailing slash to quoted args ---
quote_indent() {
    printf ' \\\n'
    for arg in "$@"; do
        printf '\t%s \\\n' "$(quote "$arg")"
    done
}

# --- escape most punctuation characters, except quotes, forward slash, and space ---
escape() {
    printf '%s' "$@" | sed -e 's/\([][!#$%&()*;<=>?\_`{|}]\)/\\\1/g;'
}

# --- escape double quotes ---
escape_dq() {
    printf '%s' "$@" | sed -e 's/"/\\"/g'
}

# --- define needed environment variables ---
setup_env() {
    # --- use command args if passed or create default ---
    case "$1" in
        # --- if we only have flags discover if command should be server or agent ---
        (-*|"")
            if [ -z "${K3S_URL}" ]; then
                CMD_K3S=server
            else
                if [ -z "${K3S_TOKEN}" ] && [ -z "${K3S_TOKEN_FILE}" ] && [ -z "${K3S_CLUSTER_SECRET}" ]; then
                    fatal "Defaulted k3s exec command to 'agent' because K3S_URL is defined, but K3S_TOKEN, K3S_TOKEN_FILE or K3S_CLUSTER_SECRET is not defined."
                fi
                CMD_K3S=agent
            fi
        ;;
        # --- command is provided ---
        (*)
            CMD_K3S=$1
            shift
        ;;
    esac

    # --- use sudo if we are not already root ---
    SUDO=sudo
    if [ $(id -u) -eq 0 ]; then
        SUDO=
    fi
}

# --- set arch and suffix, fatal if architecture not supported ---
setup_verify_arch() {
    if [ -z "$ARCH" ]; then
        ARCH=$(uname -m)
    fi
    case $ARCH in
        amd64)
            ARCH=amd64
            SUFFIX=
            ;;
        x86_64)
            ARCH=amd64
            SUFFIX=
            ;;
        *)
            fatal "Unsupported architecture $ARCH"
    esac
}

# --- verify existence of network downloader executable ---
verify_downloader() {
    # Return failure if it doesn't exist or is no executable
    [ -x "$(command -v $1)" ] || return 1

    # Set verified executable as our downloader program and return success
    DOWNLOADER=$1
    return 0
}

# --- create temporary directory and cleanup when done ---
setup_tmp() {
    TMP_DIR=$(mktemp -d -t pkbs-install.XXXXXXXXXX)
    TMP_HASH=${TMP_DIR}/k3s.hash
    TMP_BIN=${TMP_DIR}/k3s.bin
    cleanup() {
        code=$?
        set +e
        trap - EXIT
		rm -rf ${TMP_DIR}
        exit $code
    }
    trap cleanup INT EXIT
}

# --- download ---
download() {
    [ $# -eq 2 ] || fatal 'download needs exactly 2 arguments'
    cd $TMP_DIR
    case $DOWNLOADER in
        curl)
            curl -o $1 -sfL $2
            ;;
        wget)
            wget -qO $1 $2
            ;;
        *)
            fatal "Incorrect executable '$DOWNLOADER'"
            ;;
    esac

    # Abort if download command failed
    [ $? -eq 0 ] || fatal 'Download failed'
}

# --- download and verify ---
download_and_verify() {
    setup_verify_arch
    verify_downloader curl || verify_downloader wget || fatal 'Can not find curl or wget for downloading files'
    setup_tmp

	# --- required dependencies and tools ---
	local DOCKER_PKG=docker.io
	[ -r /etc/os-release ] && . /etc/os-release
    if [ "${ID_LIKE%%[ ]*}" = "suse" ]; then
		fatal 'Not tested'
        package_installer=zypper
	elif [ "${ID_LIKE%%[ ]*}" = "debian" ]; then
		package_installer=apt
	elif [ "${ID_LIKE%%[ ]*}" = "rhel fedora" ]; then
		package_installer=yum
		DOCKER_PKG=docker
	else
		fatal "Unsupported flavor: ${ID_LIKE}"
    fi

    if [ "${package_installer}" = "yum" ] && [ -x /usr/bin/dnf ]; then
        package_installer=dnf
    fi

	test -e /etc/bash_completion || \
		$SUDO $package_installer install -y bash-completion
	
	local xprog
	for xprog in make unzip ; do
		test -x "$(command -v ${xprog})" || \
			$SUDO $package_installer install -y ${xprog} || \
			fatal "Installation of ${prog} failed"
	done

	# --- Docker ---
	test -x "$(command -v docker)" || {
		$SUDO $package_installer install -y ${DOCKER_PKG} || \
			fatal "Intallation of ${DOCKER_PKG} failed"
	}
	test "0" = "$(id -u)" || {
		groups | grep -qw docker || {
			$SUDO usermod -aG ${LOGNAME} docker
			info "User ${LOGNAME} added to docker group - log out once"
		}
	}

	# --- kubectl ---
	test -x "$(command -v kubectl)" || {
		local KUBEREL="release/v1.23.0"
		info "using ${KUBEREL}"
		download ${TMP_DIR}/kubectl https://dl.k8s.io/${KUBEREL}/bin/linux/amd64/kubectl
		download ${TMP_DIR}/kubectl.sha256 https://dl.k8s.io/${KUBEREL}/bin/linux/amd64/kubectl.sha256
		( cd ${TMP_DIR} && test "$(cat kubectl.sha256)" = "$(sha256sum kubectl | awk '{print $1}')" ) || \
			fatal "kubectl checksum mismatch"
		$SUDO install -o root -g root -m 0755 ${TMP_DIR}/kubectl /usr/local/bin/kubectl
		[ -w ~/.bashrc ] && {
			grep -q 'source <(kubectl completion bash)' ~/.bashrc || \
				echo 'source <(kubectl completion bash)' >>~/.bashrc
			info '~/.bashrc modified'
		}
		info 'kubectl installed'
	}

	# --- kustomize ---
	test -x "$(command -v kustomize)" || {
		( cd $TMP_DIR && curl -s "https://raw.githubusercontent.com/kubernetes-sigs/kustomize/master/hack/install_kustomize.sh" | tee ${TMP_DIR}/install_kustomize.sh \
		| bash || fatal "Installation of kustomize failed" )
		$SUDO install -o root -g root -m 0755 ${TMP_DIR}/kustomize /usr/local/bin
		info 'kustomize installed'
	}

	# --- pkbs ---
	test -d ~/pkbs-main || {
		download ${TMP_DIR}/pkbs-main.zip https://codeload.github.com/ptrktn/pkbs/zip/refs/heads/main
		unzip -qo ${TMP_DIR}/pkbs-main.zip -d ~/
	}

	info "pkbs is ready in $(readlink -f ~/pkbs-main)"
	info "1) Configure kubectl or initialize cluster (rule bootstrap-k3s)"
	info "2) make -C ~/pkebs-main deploy-all"
	info "3) ./qsub -N HelloWorld examples/hello-world"
}

# --- re-evaluate args to include env command ---
eval set -- $(escape "${INSTALL_K3S_EXEC}") $(quote "$@")

# --- run the install process --
{
    verify_system
    setup_env "$@"
    download_and_verify
}
