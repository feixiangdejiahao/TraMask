set -eu
cd /app
git config --global --add safe.directory /app
actual=$(git rev-parse HEAD)
printf "BASE=%s\n" "$actual"
test "$actual" = 368a3572b8146cc038b3f240da6792003d7e42c5
git apply --check /candidate.patch
git apply /candidate.patch
cp /review/combination_review_test.go ./combination_review_test.go
go test -count=1 -run "^TestReview" -v .
