"""Bootstrap helpers for initial crawler skills."""
from __future__ import annotations

from .models import Skill


def default_crawler_skills() -> list[Skill]:
    """Return the three manual crawler skills required by the MVP."""
    return [
        Skill(
            skill_id="crawler_arxiv_v1",
            skill_type="crawler",
            platform="arxiv",
            source_layer="学术层",
            tool_name="search_arxiv",
            description="Search recent AI papers on arXiv.",
            logic="Use search_arxiv for recent papers, favor AI categories, and keep results recent.",
            input_template={"max_results": 10, "days": 90},
        ),
        Skill(
            skill_id="crawler_producthunt_v1",
            skill_type="crawler",
            platform="product_hunt",
            source_layer="工业层",
            tool_name="search_product_hunt",
            description="Fetch recent top AI products from Product Hunt.",
            logic="Use search_product_hunt for current top launches and keep summaries short.",
            input_template={"max_results": 10},
        ),
        Skill(
            skill_id="crawler_reddit_v1",
            skill_type="crawler",
            platform="reddit",
            source_layer="社区层",
            tool_name="search_reddit",
            description="Search Reddit discussions about AI products and models.",
            logic="Use search_reddit across relevant AI communities and favor discussions with real feedback.",
            input_template={"subreddit": "MachineLearning", "max_results": 10},
        ),
    ]
