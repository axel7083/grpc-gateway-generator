FROM golang:1.19-alpine as build

ARG project

COPY ./$project/ /$project
WORKDIR /$project

RUN mkdir -p /usr/local/go/src/$project/gen/go; cp -r ./gen/go/* /usr/local/go/src/$project/gen/go

RUN go mod tidy
RUN go build -o /gateway

FROM alpine:3.16.2

COPY --from=build /gateway .
CMD ["/gateway"]


