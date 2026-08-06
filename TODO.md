### TODO:

* [X] The agent is not following the current folder / components. (e.g: for login it created a new component instead of using the existing one)
* [ ] Currently we are using amazon nova lite, change it to opus for planning, and sonnet for coding
* [ ] fix the issue where aws is not able to parse "" in jira issue title
* [X] fix atlassian web automation access issue


For Dashboard:
* [ ] update architecture - click - architecture agent gets called and the same folder gets updated also show last synced date

* [ ] Add links to github PRs, step function workflows and JIRA ticket

* [ ] Remove executive summary section

* [ ] Add light/dark mode toggle to dashboard

* [ ] The hero component progress is not showing step by step it directly renders once all the steps are complete


For entire flow:

* [ ] Add a mechanism where if the PR generated is not correct, human should add review comment to the PR and the entire cycle should rerun and update the PR with review comment fixes. this might include minor changes to entire plan change.