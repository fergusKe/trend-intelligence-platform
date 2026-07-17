FROM spark:4.0.2-python3
# jar 版本合約：ICEBERG=§0 pin；HADOOP_AWS=3.4.1；AWS_SDK = **v2 bundle 2.24.6**——
# hadoop-aws 3.4.x 的 S3A 已遷 AWS SDK v2（software.amazon.awssdk），舊校準的 v1
# aws-java-sdk-bundle:1.12.780 會讓 driver 撞 NoClassDefFoundError: software/amazon/awssdk/...
# （實跑教訓，見 errata §F-2）。2.24.6 = hadoop-project 3.4.1 POM 的 aws-java-sdk-v2.version（查證）。
# postgresql JDBC = Iceberg JDBC catalog 必需
ARG ICEBERG_VERSION=1.11.0
ARG HADOOP_AWS_VERSION=3.4.1
ARG AWS_SDK_VERSION=2.24.6
ARG PG_JDBC_VERSION=42.7.7
ADD --chmod=644 https://repo1.maven.org/maven2/org/apache/iceberg/iceberg-spark-runtime-4.0_2.13/${ICEBERG_VERSION}/iceberg-spark-runtime-4.0_2.13-${ICEBERG_VERSION}.jar /opt/spark/jars/
ADD --chmod=644 https://repo1.maven.org/maven2/org/apache/hadoop/hadoop-aws/${HADOOP_AWS_VERSION}/hadoop-aws-${HADOOP_AWS_VERSION}.jar /opt/spark/jars/
ADD --chmod=644 https://repo1.maven.org/maven2/software/amazon/awssdk/bundle/${AWS_SDK_VERSION}/bundle-${AWS_SDK_VERSION}.jar /opt/spark/jars/
ADD --chmod=644 https://repo1.maven.org/maven2/org/postgresql/postgresql/${PG_JDBC_VERSION}/postgresql-${PG_JDBC_VERSION}.jar /opt/spark/jars/
COPY jobs/ /opt/spark/jobs/
USER spark
