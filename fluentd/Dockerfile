FROM fluent/fluentd:v1.16-1

# Install dependencies
USER root
RUN apk add --no-cache --update --virtual .build-deps \
    build-base ruby-dev \
    && gem install fluent-plugin-kafka \
    && apk del .build-deps \
    && rm -rf /tmp/* /var/tmp/* /usr/lib/ruby/gems/*/cache/*.gem

USER fluent
