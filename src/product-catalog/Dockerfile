FROM golang:1.22-alpine AS builder

WORKDIR /usr/src/app/

# Copy
COPY go.mod go.sum ./

# Download
RUN go mod download

# Copy the rest of the source code
COPY . .

# Building the binery
RUN go build -o product-catalog .  


#################################### 
#Copy the binery

FROM alpine AS release

WORKDIR /usr/src/app/

# copying the base products jason to load the products for initial check
COPY ./products/ ./products/   
COPY --from=builder /usr/src/app/product-catalog/ ./

ENV PRODUCT_CATALOG_PORT=8088
ENTRYPOINT [ "./product-catalog" ]
