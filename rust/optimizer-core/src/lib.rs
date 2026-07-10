use serde::{Deserialize, Serialize};
use std::cmp::Ordering;
use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet};
use thiserror::Error;

fn default_true() -> bool {
    true
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct PrevaluedPiece {
    pub item_id: String,
    pub position: String,
    pub set_name: String,
    pub value: Vec<f64>,
    #[serde(default)]
    pub locked_current: bool,
    #[serde(default = "default_true")]
    pub eligible: bool,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct SetRequirementInput {
    pub set_names: Vec<String>,
    pub pieces: usize,
}

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
pub struct SetPlanInput {
    #[serde(default)]
    pub requirements: Vec<SetRequirementInput>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct BestLoadoutRequest {
    pub positions: Vec<String>,
    pub pieces: Vec<PrevaluedPiece>,
    #[serde(default)]
    pub set_plan: Option<SetPlanInput>,
    #[serde(default)]
    pub require_set_plan: bool,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct BestLoadoutResult {
    pub selected_item_ids: Vec<String>,
    pub value: Vec<f64>,
    pub set_plan_satisfied: bool,
    pub set_counts: BTreeMap<String, usize>,
}

#[derive(Debug, Error, PartialEq)]
pub enum SolveError {
    #[error("positions must be unique")]
    DuplicatePosition,
    #[error("inventory item_id must be unique: {0}")]
    DuplicateItemId(String),
    #[error("piece value vector cannot be empty")]
    EmptyValueVector,
    #[error("piece value vectors have inconsistent lengths")]
    InconsistentValueVector,
    #[error("piece value vector contains a non-finite number: {0}")]
    NonFiniteValue(String),
    #[error("set requirement must contain at least one set name")]
    EmptySetRequirement,
    #[error("set requirement piece count must be positive")]
    EmptySetPieceCount,
}

#[derive(Clone, Debug)]
struct Candidate {
    value: Vec<f64>,
    selected_item_ids: Vec<String>,
}

pub fn solve_best_loadout(
    request: &BestLoadoutRequest,
) -> Result<Option<BestLoadoutResult>, SolveError> {
    validate_request(request)?;
    let Some(vector_len) = request
        .pieces
        .iter()
        .find(|piece| piece.eligible)
        .map(|piece| piece.value.len())
    else {
        return Ok(None);
    };

    let target_sets: Vec<String> = request
        .set_plan
        .iter()
        .flat_map(|plan| plan.requirements.iter())
        .flat_map(|requirement| requirement.set_names.iter().cloned())
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect();
    let set_index: BTreeMap<&str, usize> = target_sets
        .iter()
        .enumerate()
        .map(|(index, set_name)| (set_name.as_str(), index))
        .collect();

    let mut states = vec![(
        vec![0_u8; target_sets.len()],
        Candidate {
            value: vec![0.0; vector_len],
            selected_item_ids: Vec::with_capacity(request.positions.len()),
        },
    )];

    for position in &request.positions {
        let all_choices: Vec<&PrevaluedPiece> = request
            .pieces
            .iter()
            .filter(|piece| piece.eligible && piece.position == *position)
            .collect();
        let locked_choices: Vec<&PrevaluedPiece> = all_choices
            .iter()
            .copied()
            .filter(|piece| piece.locked_current)
            .collect();
        let choices = if locked_choices.is_empty() {
            all_choices
        } else {
            locked_choices
        };
        if choices.is_empty() {
            return Ok(None);
        }

        let mut next_states: Vec<(Vec<u8>, Candidate)> = Vec::new();
        let mut next_state_indexes: HashMap<Vec<u8>, usize> = HashMap::new();
        for (count_state, candidate) in &states {
            for piece in &choices {
                let mut next_count_state = count_state.clone();
                if let Some(index) = set_index.get(piece.set_name.as_str()) {
                    next_count_state[*index] = next_count_state[*index]
                        .saturating_add(1)
                        .min(request.positions.len() as u8);
                }
                let next_value = add_vectors(&candidate.value, &piece.value);
                let mut selected_item_ids = candidate.selected_item_ids.clone();
                selected_item_ids.push(piece.item_id.clone());
                let next_candidate = Candidate {
                    value: next_value,
                    selected_item_ids,
                };
                match next_state_indexes.get(&next_count_state).copied() {
                    Some(index)
                        if !lexicographically_greater(
                            &next_candidate.value,
                            &next_states[index].1.value,
                        ) => {}
                    Some(index) => {
                        next_states[index].1 = next_candidate;
                    }
                    None => {
                        next_state_indexes.insert(next_count_state.clone(), next_states.len());
                        next_states.push((next_count_state, next_candidate));
                    }
                }
            }
        }
        states = next_states;
    }

    let plan = request.set_plan.as_ref();
    let mut satisfied: Vec<&Candidate> = states
        .iter()
        .filter_map(|(state, candidate)| {
            set_plan_satisfied(plan, state, &target_sets).then_some(candidate)
        })
        .collect();
    let candidates: Vec<&Candidate> = if satisfied.is_empty() {
        if request.require_set_plan {
            return Ok(None);
        }
        states.iter().map(|(_state, candidate)| candidate).collect()
    } else {
        std::mem::take(&mut satisfied)
    };
    let Some(best) = candidates.into_iter().reduce(|best, candidate| {
        if lexicographically_greater(&candidate.value, &best.value) {
            candidate
        } else {
            best
        }
    }) else {
        return Ok(None);
    };

    let pieces_by_id: BTreeMap<&str, &PrevaluedPiece> = request
        .pieces
        .iter()
        .map(|piece| (piece.item_id.as_str(), piece))
        .collect();
    let mut set_counts = BTreeMap::new();
    for item_id in &best.selected_item_ids {
        if let Some(piece) = pieces_by_id.get(item_id.as_str()) {
            *set_counts.entry(piece.set_name.clone()).or_insert(0) += 1;
        }
    }
    let selected_state = target_sets
        .iter()
        .map(|set_name| *set_counts.get(set_name).unwrap_or(&0) as u8)
        .collect::<Vec<_>>();
    Ok(Some(BestLoadoutResult {
        selected_item_ids: best.selected_item_ids.clone(),
        value: best.value.clone(),
        set_plan_satisfied: set_plan_satisfied(plan, &selected_state, &target_sets),
        set_counts,
    }))
}

fn validate_request(request: &BestLoadoutRequest) -> Result<(), SolveError> {
    let mut positions = HashSet::new();
    if request
        .positions
        .iter()
        .any(|position| !positions.insert(position))
    {
        return Err(SolveError::DuplicatePosition);
    }
    let mut item_ids = HashSet::new();
    for piece in &request.pieces {
        if !item_ids.insert(piece.item_id.as_str()) {
            return Err(SolveError::DuplicateItemId(piece.item_id.clone()));
        }
        if piece.value.is_empty() {
            return Err(SolveError::EmptyValueVector);
        }
        if piece.value.iter().any(|value| !value.is_finite()) {
            return Err(SolveError::NonFiniteValue(piece.item_id.clone()));
        }
    }
    let vector_lengths = request
        .pieces
        .iter()
        .filter(|piece| piece.eligible)
        .map(|piece| piece.value.len())
        .collect::<BTreeSet<_>>();
    if vector_lengths.len() > 1 {
        return Err(SolveError::InconsistentValueVector);
    }
    if let Some(plan) = &request.set_plan {
        for requirement in &plan.requirements {
            if requirement.set_names.is_empty() {
                return Err(SolveError::EmptySetRequirement);
            }
            if requirement.pieces == 0 {
                return Err(SolveError::EmptySetPieceCount);
            }
        }
    }
    Ok(())
}

fn add_vectors(left: &[f64], right: &[f64]) -> Vec<f64> {
    left.iter()
        .zip(right)
        .map(|(left, right)| left + right)
        .collect()
}

fn lexicographically_greater(left: &[f64], right: &[f64]) -> bool {
    for (left_value, right_value) in left.iter().zip(right) {
        match left_value.partial_cmp(right_value) {
            Some(Ordering::Greater) => return true,
            Some(Ordering::Less) => return false,
            _ => {}
        }
    }
    false
}

fn set_plan_satisfied(plan: Option<&SetPlanInput>, state: &[u8], set_names: &[String]) -> bool {
    let Some(plan) = plan else {
        return true;
    };
    if plan.requirements.is_empty() {
        return true;
    }
    let mut remaining: BTreeMap<String, usize> = set_names
        .iter()
        .zip(state)
        .map(|(set_name, count)| (set_name.clone(), *count as usize))
        .collect();
    requirements_satisfied(&plan.requirements, 0, &mut remaining)
}

fn requirements_satisfied(
    requirements: &[SetRequirementInput],
    index: usize,
    remaining: &mut BTreeMap<String, usize>,
) -> bool {
    if index >= requirements.len() {
        return true;
    }
    let requirement = &requirements[index];
    for set_name in &requirement.set_names {
        let available = *remaining.get(set_name.as_str()).unwrap_or(&0);
        if available < requirement.pieces {
            continue;
        }
        remaining.insert(set_name.clone(), available - requirement.pieces);
        if requirements_satisfied(requirements, index + 1, remaining) {
            remaining.insert(set_name.clone(), available);
            return true;
        }
        remaining.insert(set_name.clone(), available);
    }
    false
}

#[cfg(test)]
mod tests {
    use super::{solve_best_loadout, BestLoadoutRequest, BestLoadoutResult};
    use serde::Deserialize;

    #[derive(Deserialize)]
    struct GoldenFixture {
        cases: Vec<GoldenCase>,
    }

    #[derive(Deserialize)]
    struct GoldenCase {
        name: String,
        request: BestLoadoutRequest,
        expected: Option<BestLoadoutResult>,
    }

    #[test]
    fn matches_python_position_ev_golden_cases() {
        let fixture: GoldenFixture = serde_json::from_str(include_str!(
            "../../../tests/fixtures/rust_best_loadout_golden.json"
        ))
        .expect("valid golden fixture");
        for case in fixture.cases {
            let actual = solve_best_loadout(&case.request).expect("valid request");
            assert_eq!(actual, case.expected, "golden case {}", case.name);
        }
    }
}
