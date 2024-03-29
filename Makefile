MODULE      = pkbs
NS          = $(MODULE)
SNS         = $(MODULE)-system
REGISTRY    = docker.io/pkbs
XREGISTRY   = $(REGISTRY)
NEXTCLOUD   = 1
AUTOPEP8    = autopep8 --in-place --aggressive --aggressive --max-line-length 128

# local registry
# REGISTRY    = registry.localdomain
# XREGISTRY   = $(REGISTRY):5000

MY_GCP_LOGIN      ?= MODIFY_THIS_OR_SET_ENV_VARIABLE
MY_GCP_PROJECT_ID ?= MODIFY_THIS_OR_SET_ENV_VARIABLE
MY_GCP_CLUSTER    ?= pkbs-cluster
# Hamina in Finland is a good choice
MY_GCP_ZONE       ?= europe-north1-b



# FIXME default rule
.PHONY: install
install:
	/bin/false

rsyslog-config: rsyslog.conf
	echo "RSYSLOG_CONFIG_BASE64=`base64 -w 0 < rsyslog.conf`" > $@

.PHONY: env-configmap
env-configmap: rsyslog-config
	kubectl create configmap env-config --from-env-file=env-config --dry-run=client -o yaml | kubectl -n $(NS) apply -f -

.PHONY: deploy-all
deploy-all: deploy-system deploy

.PHONY: deploy-system
deploy-system: rsyslog-config
	kubectl create ns $(SNS) 2> /dev/null || true
	kubectl get ns $(SNS)
	kubectl create configmap rsyslog-config --from-env-file=rsyslog-config --dry-run=client -o yaml | kubectl -n $(SNS) apply -f -
	$(MAKE) NS=$(SNS) env-configmap
	[ 0 -eq $(NEXTCLOUD) ] || kubectl -n $(SNS) apply -f manifests/nextcloud.yaml
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
build: tidy-sources
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

.PHONY: local-registry-test
local-registry-test:
	$(MAKE) REGISTRY=registry.localdomain XREGISTRY=registry.localdomain:5000 reconfigure-registry xreload

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
	./dispatcher.py --syslog -s nats://localhost:14222  -c "sleep 1"
	./worker.py --syslog -s nats://localhost:14222 --max-jobs 1
	./qstat.py -s nats://localhost:14222

# FIXME https://docs.ansible.com/ansible/2.7/modules/gcp_container_cluster_module.html
.PHONY: bootstrap-gcp
bootstrap-gcp:
	gcloud auth print-access-token $(MY_GCP_LOGIN) > /dev/null 2>&1 || gcloud auth login $(MY_GCP_LOGIN)
	gcloud config get-value project | gcloud config get-value project | grep -v -q -F "(unset)" || gcloud config set project $(MY_GCP_PROJECT_ID)
	test "$(MY_GCP_PROJECT_ID)" = "`gcloud config get-value project`"
	(gcloud services list | grep -w container.googleapis.com) || gcloud services enable container.googleapis.com
	test "" != "`gcloud container clusters list | grep -w $(MY_GCP_CLUSTER)`" || gcloud container clusters create $(MY_GCP_CLUSTER) --zone=$(MY_GCP_ZONE) --release-channel=rapid --cluster-version=1.22
	gcloud container clusters get-credentials $(MY_GCP_CLUSTER) --zone=$(MY_GCP_ZONE)

.PHONY: test-gcp
test-gcp:
	gcloud container clusters list | grep -w $(MY_GCP_CLUSTER) | grep -w RUNNING

.PHONY: clean-gcp
clean-gcp:
	@echo "ATTENTION: $(MY_GCP_CLUSTER) cluster in $(MY_GCP_ZONE) will be deleted in 30 secs!"
	@echo "Press CTRL-C to interrupt."
	sleep 30
	gcloud container clusters delete $(MY_GCP_CLUSTER) --zone=$(MY_GCP_ZONE)

.PHONY: tidy-sources
tidy-sources:
	for i in *.py ; \
       do echo Checking file $$i ; \
       test -x "$$i" || exit 1 ; \
       python3 -m py_compile $$i || exit 1 ; \
       $(AUTOPEP8) $$i || exit 1 ; \
    done ; rm -fr __pycache__
	find manifests -type f -name '*.yaml' -exec kustomize cfg fmt {} \;

.PHONY: test-deploy
test-deploy:
	kubectl -n $(NS) get po ; \
	NAME=`dd if=/dev/random count=1 2> /dev/null | sha1sum | \
	awk '{print $$1}'` ; \
	./qsub -N test-deploy-$$NAME examples/hello-world ; \
	sleep 60 # FIXME ; \
	kubectl -n $(SNS) exec rsyslog -- cat /logs/messages.log | \
	grep "Hello, World! I'm test-deploy-$${NAME}, a batch job." || exit 1

.PHONY: test-build-deploy
test-build-deploy: xreload test-deploy

.PHONY: nextcloud-port-forward
nextcloud-port-forward:
	kubectl -n $(SNS) port-forward nextcloud-ss-0 8080:80

.PHONY: install-metrics-server
install-metrics-server:
	kubectl -n kube-system get deployments.apps metrics-server || kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
