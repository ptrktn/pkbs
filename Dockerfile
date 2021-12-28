FROM alpine

WORKDIR /usr/src/app

COPY ./Dockerfile ./dispatcher.py ./worker.py ./qstat.py ./

RUN apk add --no-cache python3 py3-pip py3-requests libmagic && \
#    gcc gnuplot
	pip3 install nats-py && \
	pip3 install python-magic && \
	pip3 install nanoid && \
    rm -fr /root/.cache

CMD ["./worker.py"]
