use std::sync::Arc;

use daft_dsl::{AggExpr, Expr};

use crate::physical_plan::PhysicalPlan;
use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Aggregate {
    /// Aggregations to apply.
    pub aggregations: Vec<AggExpr>,

    /// Grouping to apply.
    pub groupby: Vec<Expr>,

    // Upstream node.
    pub input: Arc<PhysicalPlan>,
}

impl Aggregate {
    pub(crate) fn new(
        input: Arc<PhysicalPlan>,
        aggregations: Vec<AggExpr>,
        groupby: Vec<Expr>,
    ) -> Self {
        Self {
            aggregations,
            groupby,
            input,
        }
    }
}