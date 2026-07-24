FROM maven:3.9-eclipse-temurin-21 AS builder

WORKDIR /build
COPY pom.xml .
COPY src/ src/
RUN mvn package -DskipTests -q

# Runtime
FROM eclipse-temurin:21-jre
WORKDIR /app
COPY --from=builder /build/target/*.jar app.jar

EXPOSE 9091 8081
ENTRYPOINT ["java", "-jar", "app.jar"]
