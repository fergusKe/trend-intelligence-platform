FROM spark:4.0.2-python3
# jar 版本合約：ICEBERG=§0 pin；HADOOP_AWS/AWS_SDK = Task 0 C3 校準（預設傾向 3.4.1/1.12.780）；
# postgresql JDBC = Iceberg JDBC catalog 必需
ARG ICEBERG_VERSION=1.11.0
ARG HADOOP_AWS_VERSION=3.4.1
ARG AWS_SDK_VERSION=1.12.780
ARG PG_JDBC_VERSION=42.7.7
ADD --chmod=644 https://repo1.maven.org/maven2/org/apache/iceberg/iceberg-spark-runtime-4.0_2.13/${ICEBERG_VERSION}/iceberg-spark-runtime-4.0_2.13-${ICEBERG_VERSION}.jar /opt/spark/jars/
ADD --chmod=644 https://repo1.maven.org/maven2/org/apache/hadoop/hadoop-aws/${HADOOP_AWS_VERSION}/hadoop-aws-${HADOOP_AWS_VERSION}.jar /opt/spark/jars/
ADD --chmod=644 https://repo1.maven.org/maven2/com/amazonaws/aws-java-sdk-bundle/${AWS_SDK_VERSION}/aws-java-sdk-bundle-${AWS_SDK_VERSION}.jar /opt/spark/jars/
ADD --chmod=644 https://repo1.maven.org/maven2/org/postgresql/postgresql/${PG_JDBC_VERSION}/postgresql-${PG_JDBC_VERSION}.jar /opt/spark/jars/
COPY jobs/ /opt/spark/jobs/
USER spark
