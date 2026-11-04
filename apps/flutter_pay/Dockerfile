# Builds only the Flutter web client. The existing payment API, workers, and
# merchant portal are not part of this image.
FROM ghcr.io/cirruslabs/flutter:stable AS build
WORKDIR /src
RUN flutter config --enable-web && flutter create --platforms=web --project-name ithutepay_mobile .
COPY pubspec.yaml ./pubspec.yaml
COPY lib/ ./lib/
RUN flutter pub get && flutter build web --release

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /src/build/web/ /usr/share/nginx/html/
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD wget -q -O /dev/null http://127.0.0.1/healthz || exit 1
