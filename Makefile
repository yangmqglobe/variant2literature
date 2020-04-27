CURRENT_DIR = $(shell pwd)
DOCKER_HOST = $(shell ip -4 addr show docker0 | grep -Po 'inet \K[\d.]+')

MYSQL_PORT=55688
MYSQL_ROOT_PASSWORD=s8fjYJd92oP
MYSQL_VOLUME=${CURRENT_DIR}/mysql_data

CUDA_VISIBLE_DEVICES=0
NUM_PROCESSES = $(shell echo "`nproc` / 2"|bc)
NUM_TABLE_DETECTORS=1

IMAGE_NAME=variant2literature
CONTAINER_NAME=v2l
MYSQL_NAME=v2l_mysql

SHELL = /bin/sh

UID = $(shell id -u)
GID = $(shell id -g)

PMC = $(shell realpath data/pmc)
PAPER_DATA = $(shell realpath data/paper_data)

build:
	docker build -t ${IMAGE_NAME} .

compile:
	docker run --gpus all --rm --name ${CONTAINER_NAME} \
		-v ${CURRENT_DIR}:/app \
		${IMAGE_NAME} \
		bash -c "cd table_detector/lib && bash make.sh"

run:
	docker run --gpus all -d --name ${CONTAINER_NAME} \
		-v ${CURRENT_DIR}:/app \
		-v ${PMC}:/app/data/pmc \
		-v ${PAPER_DATA}:/app/data/paper_data \
		-e MYSQL_HOST=${DOCKER_HOST} \
		-e MYSQL_PORT=${MYSQL_PORT} \
		-e MYSQL_ROOT_PASSWORD=${MYSQL_ROOT_PASSWORD} \
		-e CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES} \
		-e NUM_TABLE_DETECTORS=${NUM_TABLE_DETECTORS} \
		-e LOAD_BALANCER_HOST='localhost' \
		${IMAGE_NAME} \
		bash -c "cd table_detector && python table_detector.py"

run-db:
	docker run -d --name ${MYSQL_NAME} \
		-v ${CURRENT_DIR}:/app \
		-v ${MYSQL_VOLUME}:/var/lib/mysql \
		-p ${MYSQL_PORT}:3306 \
		-e MYSQL_ROOT_PASSWORD=${MYSQL_ROOT_PASSWORD} \
		mariadb:10.3.9-bionic

load-db:
	docker exec -it ${CONTAINER_NAME} \
		bash -c "cd mysqldb && python models.py"

dump-db:
	docker exec -it ${MYSQL_NAME} \
		bash -c 'mysqldump --add-drop-database --password=${MYSQL_ROOT_PASSWORD} --opt --where="1 limit 1000" gene > /app/${MYSQL_NAME}.sql'

bash:
	docker exec -it ${CONTAINER_NAME} bash

#index:
#	docker exec -it ${CONTAINER_NAME} python main.py --n-process ${NUM_PROCESSES}

index:
	docker exec -itu ${UID}:${GID} ${CONTAINER_NAME} python index.py --n-process ${NUM_PROCESSES}

query:
	docker exec -it ${CONTAINER_NAME} python query.py ${OUTPUT_FILE}

rm:
	docker stop ${CONTAINER_NAME}
	docker rm ${CONTAINER_NAME}

rm-db:
	docker stop ${MYSQL_NAME}
	docker rm ${MYSQL_NAME}

truncate:
	docker exec -it ${CONTAINER_NAME} \
		bash -c "cd mysqldb && python truncate.py"
