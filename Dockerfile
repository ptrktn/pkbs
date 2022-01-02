FROM alpine

WORKDIR /usr/src/app

COPY ./Dockerfile ./dispatcher.py ./worker.py ./qstat.py ./requirements.txt ./

RUN apk add --no-cache python3 py3-pip py3-requests libmagic logger && \
#   Additional packages can be plugged in here
#   build-base gnuplot
	pip3 install -r requirements.txt && \
    rm -fr /root/.cache

CMD ["./worker.py"]
