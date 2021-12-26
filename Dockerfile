FROM alpine

WORKDIR /usr/src/app

COPY ./nats ./Dockerfile ./dispatcher.py ./worker.py ./

RUN apk add --no-cache python3 py3-pip unzip \
    gcc gnuplot libmagic && \
	pip3 install nats-py && \
	pip3 install python-magic && \
    rm -fr /root/.cache

CMD ["./worker.py"]
