#!/bin/sh

set -e

grep -q '^PermitRootLogin yes$' /etc/ssh/sshd_config  || {
	echo "PermitRootLogin yes" >> /etc/ssh/sshd_config 
	service sshd reload
}

# Alpine does not ship with GNU sed... - hack this
# sed -i 's:(# )http.*/v.*/community::' /etc/apk/repositories
grep -q '^http.*/community$' /etc/apk/repositories || {
	grep -m 1 community /etc/apk/repositories | \
		awk '{ print $2}' >> /etc/apk/repositories
}

test -x "$(command -v curl)" || {
	apk --no-cache add docker curl
}

service docker status > /dev/null 2>&1 || {
	apk update
	apk --no-cache add docker
	rc-update add docker boot
	service docker start
	service docker status
}

test -f /etc/rancher/k3s/registries.yaml || {
	install -d /etc/rancher/k3s
	cat <<EOF > /etc/rancher/k3s/registries.yaml
mirrors:
  "registry.localdomain":
    endpoint:
      - "http://registry.localdomain:5000"
EOF
}

test -x "$(command -v k3s)" || {
	curl -sfL https://get.k3s.io | tee k3s_install.sh | sh -s - agent
}

