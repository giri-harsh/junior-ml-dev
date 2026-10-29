cd /c/Work/Projects/junior-ml-dev
uv run python -m benchmarks.agent_dev --flaml-budget 15 --selection cv --planner scripted --out-name s22_dev_scripted_cv > /tmp/s22_b.log 2>&1
uv run python -m benchmarks.agent_dev --flaml-budget 15 --selection holdout --planner llm1 --out-name s22_dev_llm1_holdout > /tmp/s22_c.log 2>&1
uv run python -m benchmarks.agent_dev --flaml-budget 15 --selection cv --planner llm2 --out-name s22_dev_llm2_cv > /tmp/s22_d.log 2>&1
echo done > /tmp/s22_done
