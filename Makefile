MODULE      = pkbs
NS          = $(MODULE)
SNS         = $(MODULE)-system
REGISTRY    = registry.localdomain
XREGISTRY   = $(REGISTRY):5000

# FIXME default rule
.PHONY: install
install:
	/bin/false

rsyslog-config: rsyslog.conf
	echo "RSYSLOG_CONFIG_BASE64=`base64 -w 0 < rsyslog.conf`" >> $@

.PHONY: env-configmap
env-configmap: rsyslog-config
	kubectl create configmap env-config --from-env-file=env-config --dry-run=client -o yaml | kubectl -n $(NS) apply -f -

.PHONY: deploy-system
deploy-system: rsyslog-config
	kubectl create ns $(SNS) 2> /dev/null || true
	kubectl get ns $(SNS)
	kubectl create configmap rsyslog-config --from-env-file=rsyslog-config --dry-run=client -o yaml | kubectl -n $(SNS) apply -f -
	$(MAKE) NS=$(SNS) env-configmap
	kubectl -n $(SNS) apply -f manifests/nextcloud.yaml
	kubectl -n $(SNS) apply -f manifests/rsyslog.yaml
	kubectl -n $(SNS) apply -f manifests/ingress.yaml

.PHONY: clean-system
clean-system:
	kubectl delete --ignore-not-found=true ns $(SNS)

.PHONY: namespace
namespace:
	kubectl get ns $(NS) 2> /dev/null || kubectl create ns $(NS)

.PHONY: deploy
deploy: namespace env-configmap
	kustomize build . > /dev/null
	kustomize build . | kubectl -n $(NS) apply -f -

.PHONY: clean-deploy
clean-deploy:
	kubectl delete --ignore-not-found=true ns $(NS)

.PHONY: bootstrap-k3s
bootstrap-k3s:
	curl -sfL https://get.k3s.io | tee k3s_install.sh | sh -s - server --write-kubeconfig-mode "0644" --cluster-init
	install -d $(HOME)/.kube
	install -m 0600 /etc/rancher/k3s/k3s.yaml $(HOME)/.kube/config
	$(MAKE) deploy

.PHONY: clean-k3s
clean-k3s:
	k3s-uninstall.sh

.PHONY: install-nats
install-nats:
	helm repo add nats https://nats-io.github.io/k8s/helm/charts/
	helm repo update
	helm install my-nats --set auth.enabled=true,auth.user=my-user,auth.password=T0pS3cr3t nats/nats

.PHONY: start-registry
start-registry:
	test -d /var/tmp/registry || install -d /var/tmp/registry
	(docker ps | grep -qw registry) || docker run -d -p 5000:5000 --restart=always --name registry -v /var/tmp/registry:/var/lib/registry registry:2

.PHONY: stop-registry
stop-registry:
	(docker ps | grep -qw registry) && docker container stop registry

.PHONY: build
build:
	for i in *.py ; do echo Checking file $$i ; python3 -m py_compile $$i || exit 1 ; test -x "$$i" || exit 1 ; done ; rm -fr __pycache__
	docker build . -t $(MODULE)-worker
	docker tag $(MODULE)-worker $(XREGISTRY)/$(MODULE)-worker
	docker push $(XREGISTRY)/$(MODULE)-worker

.PHONY: clean
clean:
	rm -f nats-server.zip nats-client.zip k3s_install.sh nats

.PHONY: xreload
xreload:
	$(MAKE) build
	kubectl -n $(NS) delete pod --ignore-not-found=true dispatcher
	kubectl -n $(NS) scale --replicas=0 deployment worker-dep
	$(MAKE) deploy

.PHONY: reconfigure-registry
reconfigure-registry:
	kustomize edit set image WORKER_IMAGE=$(REGISTRY)/pkbs-worker:latest

.PHONY: configure-k3s-agent
configure-k3s-agent:
	test "" != "$(AGENT_NODE)"
	timeout 30s ssh -l root $(AGENT_NODE) /bin/true || (test "" != "$(SSHPASS)" && sshpass -v -e ssh-copy-id -l root $(AGENT_NODE))
	scp -q misc/configure-k3s-alpine-agent.sh root@$(AGENT_NODE):
	ssh -l root $(AGENT_NODE) "K3S_TOKEN='`sudo cat /var/lib/rancher/k3s/server/node-token`' K3S_URL=https://`hostname -I | awk '{print $$1}'`:6443 sh ./configure-k3s-alpine-agent.sh"

nats-server:
	install -m 755 -d $(dir $@)
	test -f nats-server.zip || curl -sL https://github.com/nats-io/nats-server/releases/download/v2.6.5/nats-server-v2.6.5-linux-amd64.zip -o nats-server.zip
	unzip -j nats-server.zip "*/nats-server"

nats:
	test -f nats-client.zip || curl -sL https://github.com/nats-io/natscli/releases/download/v0.0.28/nats-0.0.28-linux-amd64.zip -o nats-client.zip
	unzip -j nats-client.zip "*/nats"

.PHONY: start-nats
start-nats: $(NATS_SERVER)
	([ -z "`pgrep -u $$LOGNAME nats-server`" ] && (screen -S nats -d -m ./nats-server -p 14222 -js && sleep 5)) || /bin/true
	./nats -s nats://127.0.0.1:14222 account info

.PHONY: stop-nats
stop-nats: $(NATS_SERVER)
	( [ ! -z "`pgrep -u $$LOGNAME nats-server`" ] && kill `pgrep -u $$LOGNAME nats-server` ) || /bin/true

.PHONY: xdeps
xdeps:
	sudo apt-get install -y netcat screen

.PHONY: test
test: nats-server nats
	$(MAKE) start-nats
	./dispatcher.py -s nats://localhost:14222  -c "sleep 1"
	./worker.py -s nats://localhost:14222 --max-jobs 1
	./qstat.py -s nats://localhost:14222
