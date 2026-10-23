// Deliberate fail-closed integration boundary for the PARTIAL authoring handoff.
// The impact owner has not published its request/proposedChanges/allowedActions
// wire schema. Never send a guessed impact mutation or advertise a usable route.
// Resume this lane to implement the adapter against that published schema.
export const impactContractValidated = false;
