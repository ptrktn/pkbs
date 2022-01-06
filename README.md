# pkbs - Personal Kubernetes Batch System

## About

This software harnesses Kubernetes to run batch jobs.

## Design

![k8s design](./doc/design.svg)

## Getting Started

### Prerequisites

* GNU/Linux workstation or server, virtual machine (VM) works fine
* [GNU Make](https://www.gnu.org/software/make/)
* [Docker](https://docs.docker.com/get-docker/)
* [kubectl](https://kubernetes.io/docs/tasks/tools/)
* [kustomize](https://kubectl.docs.kubernetes.io/installation/kustomize/)
* Kubernetes cluster
* Optional: access to an external WebDAV (e.g., [NextCloud](https://nextcloud.com)) service

### Installation

### Submitting batch jobs

Commands can be read from standard input.
```
echo "echo 'Hello, World!'" | qsub -N HelloWorld
```
The `qsub` can be invoked with an executable file as an argument.
```
qsub -N ScriptedJob job.sh
```
The `qsub` can be invoked with a directory name as an argument. In this case, the directory must include a file named `run.sh` at the top level. The contents of the directory is then zipped up and submitted for scheduling. There zip file can be at most 1 MB.
```
qsub -N JobFromDirectory ~/example/job
```
In all cases the payload can be up to 1 MB.

## Contributing

All contributions are welcome. Bug reports, suggestions and feature
requests can be reported by creating a new
[issue](https://github.com/ptrktn/pkbs/issues). Code and
documentation contributions should be provided by creating a [pull
request](https://github.com/ptrktn/pkbs/pulls) (here is a good
[tutorial](https://www.dataschool.io/how-to-contribute-on-github/)).

## License

Licensed under the GNU General Public License Version 3, refer to the
file [LICENSE](LICENSE) for more information.

## Acknowledgments

* University of Helsinki, for their [DevOps with Kubernetes](https://devopswithkubernetes.com/) course.
