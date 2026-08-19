FROM eclipse-temurin:21-jdk AS builder
# For build stage using the jdk image 

WORKDIR /usr/src/app/

COPY gradlew* settings.gradle* build.gradle .
COPY ./gradle ./gradle

RUN chmod +x ./gradlew
RUN ./gradlew
# Downloads all the dependencies of the project
RUN ./gradlew downloadRepos

COPY . .
COPY ./pb ./proto
RUN chmod +x ./gradlew
# Proto has inter-service dependency methods 
RUN ./gradlew installDist -PprotoSourceDir=./proto

#####################################################
# JRE is needed to run java application but compilation is done thus excluded jdk
FROM eclipse-temurin:21-jre

WORKDIR /usr/src/app/

COPY --from=builder /usr/src/app/ ./

ENV AD_PORT 9099

ENTRYPOINT ["./build/install/opentelemetry-demo-ad/bin/Ad"]

