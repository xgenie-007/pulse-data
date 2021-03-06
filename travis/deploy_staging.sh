source travis/base.sh

# Create encryption keys and authenticate with GAE
openssl aes-256-cbc -K $encrypted_7ad4439b42dc_key -iv $encrypted_7ad4439b42dc_iv -in client-secret-staging.json.enc -out client-secret-staging.json -d 2>&1 | ind
gcloud -q auth activate-service-account recidiviz-staging@appspot.gserviceaccount.com --key-file client-secret-staging.json 2>&1 | ind

# Deploy cron.yaml
gcloud -q app deploy cron.yaml --project=recidiviz-staging 2>&1 | ind

# Initialize task queues
docker exec -it recidiviz pipenv run python -m recidiviz.tools.initialize_google_cloud_task_queues --project_id recidiviz-staging --google_auth_token $(gcloud auth print-access-token) 2>&1 | ind

# App engine doesn't allow '.' in the version name
VERSION=$(echo $TRAVIS_TAG | tr '.' '-')
echo $VERSION 2>&1 | ind

# Authorize docker to acess GCR
# use instead of 'auth configure-docker' as travis has an old gcloud
gcloud -q docker --authorize-only 2>&1 | ind

# Push the docker image to GCR
IMAGE_URL=us.gcr.io/recidiviz-staging/appengine/default.$VERSION:latest
echo $IMAGE_URL 2>&1 | ind
docker tag recidiviz-image $IMAGE_URL 2>&1 | ind
docker push $IMAGE_URL 2>&1 | ind

# Deploy application
gcloud -q app deploy staging.yaml --project recidiviz-staging --version $VERSION --image-url $IMAGE_URL 2>&1 | ind
