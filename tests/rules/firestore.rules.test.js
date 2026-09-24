/**
 * Firestore security-rule tests for SwapCycle.
 *
 * Setup (once, from the project root):
 *   npm i -D @firebase/rules-unit-testing firebase
 *
 * Run (needs Java installed for the emulator):
 *   firebase emulators:exec --only firestore "node --test tests/rules/"
 */
const { test, describe, before, beforeEach, after } = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const {
  initializeTestEnvironment,
  assertFails,
  assertSucceeds,
} = require('@firebase/rules-unit-testing');
const {
  doc, getDoc, setDoc, updateDoc, deleteDoc, serverTimestamp, Timestamp,
} = require('firebase/firestore');

let env;

const RULES = fs.readFileSync(
  path.join(__dirname, '..', '..', 'firestore.rules'), 'utf8');

/** A signed-in, verified @qiu.edu.my user. */
const qiu = (uid) =>
  env.authenticatedContext(uid, {
    email: `${uid}@qiu.edu.my`,
    email_verified: true,
  }).firestore();

const seed = (fn) => env.withSecurityRulesDisabled((ctx) => fn(ctx.firestore()));

const MATCH = 'matches/m1';
const CYCLE = ['alice', 'bob', 'carol'];

const seedMatch = (data = {}) => seed((db) =>
  setDoc(doc(db, MATCH), {
    cycle: CYCLE,
    status: 'pending',
    confirmations: {},
    receipts: {},
    ...data,
  }));

before(async () => {
  env = await initializeTestEnvironment({
    projectId: 'swapcycle-rules-test',
    firestore: { rules: RULES },
  });
});
after(async () => { await env.cleanup(); });
beforeEach(async () => { await env.clearFirestore(); });

// ---------------------------------------------------------------------------
describe('authentication', () => {
  test('signed-out users cannot read listings', async () => {
    const db = env.unauthenticatedContext().firestore();
    await assertFails(getDoc(doc(db, 'listings/l1')));
  });

  test('non-QIU accounts are rejected', async () => {
    const db = env.authenticatedContext('eve', {
      email: 'eve@gmail.com', email_verified: true,
    }).firestore();
    await assertFails(getDoc(doc(db, 'listings/l1')));
  });

  test('unverified QIU email is rejected', async () => {
    const db = env.authenticatedContext('eve', {
      email: 'eve@qiu.edu.my', email_verified: false,
    }).firestore();
    await assertFails(getDoc(doc(db, 'listings/l1')));
  });

  test('look-alike domain is rejected', async () => {
    const db = env.authenticatedContext('eve', {
      email: 'eve@qiu.edu.my.evil.com', email_verified: true,
    }).firestore();
    await assertFails(getDoc(doc(db, 'listings/l1')));
  });

  test('verified QIU user can read listings', async () => {
    await assertSucceeds(getDoc(doc(qiu('alice'), 'listings/l1')));
  });
});

// ---------------------------------------------------------------------------
describe('listings', () => {
  test('owner can create their own listing', async () => {
    await assertSucceeds(setDoc(doc(qiu('alice'), 'listings/l1'), { ownerId: 'alice' }));
  });

  test('cannot create a listing owned by someone else', async () => {
    await assertFails(setDoc(doc(qiu('alice'), 'listings/l1'), { ownerId: 'bob' }));
  });

  test('cannot edit or delete another user\'s listing', async () => {
    await seed((db) => setDoc(doc(db, 'listings/l1'), { ownerId: 'bob', item: 'guitar' }));
    await assertFails(updateDoc(doc(qiu('alice'), 'listings/l1'), { item: 'stolen' }));
    await assertFails(deleteDoc(doc(qiu('alice'), 'listings/l1')));
    await assertSucceeds(deleteDoc(doc(qiu('bob'), 'listings/l1')));
  });

  test('owner cannot hand a listing to someone else', async () => {
    await seed((db) => setDoc(doc(db, 'listings/l1'), { ownerId: 'alice' }));
    await assertFails(updateDoc(doc(qiu('alice'), 'listings/l1'), { ownerId: 'bob' }));
  });
});

// ---------------------------------------------------------------------------
describe('preferences', () => {
  test('a user can read only their own preferences', async () => {
    await seed((db) => setDoc(doc(db, 'preferences/p1'), { userId: 'alice' }));
    await assertSucceeds(getDoc(doc(qiu('alice'), 'preferences/p1')));
    await assertFails(getDoc(doc(qiu('bob'), 'preferences/p1')));
  });

  test('cannot submit a preference for someone else', async () => {
    await assertFails(setDoc(doc(qiu('alice'), 'preferences/p1'), { userId: 'bob' }));
    await assertSucceeds(setDoc(doc(qiu('alice'), 'preferences/p2'), { userId: 'alice' }));
  });

  test('preferences cannot be edited or deleted by clients', async () => {
    await seed((db) => setDoc(doc(db, 'preferences/p1'), { userId: 'alice' }));
    await assertFails(updateDoc(doc(qiu('alice'), 'preferences/p1'), { rawText: 'x' }));
    await assertFails(deleteDoc(doc(qiu('alice'), 'preferences/p1')));
  });
});

// ---------------------------------------------------------------------------
describe('matches', () => {
  test('clients cannot create or delete matches', async () => {
    await assertFails(setDoc(doc(qiu('alice'), 'matches/fake'), { cycle: ['alice', 'bob'] }));
    await seedMatch();
    await assertFails(deleteDoc(doc(qiu('alice'), MATCH)));
  });

  test('a participant can confirm for themselves', async () => {
    await seedMatch();
    await assertSucceeds(updateDoc(doc(qiu('alice'), MATCH), { 'confirmations.alice': true }));
  });

  test('cannot confirm on behalf of someone else', async () => {
    await seedMatch();
    await assertFails(updateDoc(doc(qiu('alice'), MATCH), { 'confirmations.bob': true }));
  });

  test('non-participants cannot touch the match', async () => {
    await seedMatch();
    await assertFails(updateDoc(doc(qiu('dave'), MATCH), { 'confirmations.dave': true }));
  });

  test('cannot mark the trade confirmed until everyone confirmed', async () => {
    await seedMatch({ confirmations: { alice: true } });
    await assertFails(updateDoc(doc(qiu('bob'), MATCH), {
      'confirmations.bob': true, status: 'confirmed',
    }));
  });

  test('the last confirmation flips the status to confirmed', async () => {
    await seedMatch({ confirmations: { alice: true, bob: true } });
    await assertSucceeds(updateDoc(doc(qiu('carol'), MATCH), {
      'confirmations.carol': true, status: 'confirmed',
    }));
  });

  test('a participant can decline a pending trade', async () => {
    await seedMatch();
    await assertSucceeds(updateDoc(doc(qiu('alice'), MATCH), { status: 'declined' }));
  });

  test('clients cannot edit protected fields', async () => {
    await seedMatch();
    await assertFails(updateDoc(doc(qiu('alice'), MATCH), { cycle: ['alice', 'dave'] }));
    await assertFails(updateDoc(doc(qiu('alice'), MATCH), { totalUtility: 99 }));
    await assertFails(updateDoc(doc(qiu('alice'), MATCH), { aiEvaluation: { reason: 'hi' } }));
  });

  test('receipt cannot be recorded before the trade is confirmed', async () => {
    await seedMatch();
    await assertFails(updateDoc(doc(qiu('alice'), MATCH), { 'receipts.alice': true }));
  });

  test('receipt can be recorded once confirmed, only for yourself', async () => {
    await seedMatch({ status: 'confirmed', confirmations: { alice: true, bob: true, carol: true } });
    await assertSucceeds(updateDoc(doc(qiu('alice'), MATCH), { 'receipts.alice': true }));
    await assertFails(updateDoc(doc(qiu('alice'), MATCH), { 'receipts.bob': true }));
  });

  test('cannot complete the trade until everyone received', async () => {
    await seedMatch({ status: 'confirmed', receipts: { alice: true } });
    await assertFails(updateDoc(doc(qiu('bob'), MATCH), {
      'receipts.bob': true, status: 'completed',
    }));
  });

  test('the last receipt completes the trade', async () => {
    await seedMatch({ status: 'confirmed', receipts: { alice: true, bob: true } });
    await assertSucceeds(updateDoc(doc(qiu('carol'), MATCH), {
      'receipts.carol': true, status: 'completed',
    }));
  });

  test('cannot skip straight from pending to completed', async () => {
    await seedMatch({ receipts: { alice: true, bob: true } });
    await assertFails(updateDoc(doc(qiu('carol'), MATCH), {
      'receipts.carol': true, status: 'completed',
    }));
  });

  test('completed and declined matches are frozen', async () => {
    await seedMatch({ status: 'completed' });
    await assertFails(updateDoc(doc(qiu('alice'), MATCH), { status: 'declined' }));
    await env.clearFirestore();
    await seedMatch({ status: 'declined' });
    await assertFails(updateDoc(doc(qiu('alice'), MATCH), { status: 'pending' }));
  });
});

// ---------------------------------------------------------------------------
describe('private chat', () => {
  const chat = (chatId, id = 'msg1') => `${MATCH}/chats/${chatId}/messages/${id}`;
  const text = (uid, extra = {}) => ({
    type: 'text', text: 'hi', senderId: uid, senderName: uid, createdAt: serverTimestamp(), ...extra,
  });

  beforeEach(async () => { await seedMatch(); });

  test('the two people in a chat can write and read', async () => {
    await assertSucceeds(setDoc(doc(qiu('alice'), chat('alice_bob')), text('alice')));
    await assertSucceeds(getDoc(doc(qiu('bob'), chat('alice_bob'))));
  });

  test('a third cycle member cannot read someone else\'s chat', async () => {
    await seed((db) => setDoc(doc(db, chat('alice_bob')), { type: 'text', text: 'secret', senderId: 'alice' }));
    await assertFails(getDoc(doc(qiu('carol'), chat('alice_bob'))));
    await assertFails(setDoc(doc(qiu('carol'), chat('alice_bob', 'm2')), text('carol')));
  });

  test('users outside the match cannot read or write', async () => {
    await seed((db) => setDoc(doc(db, chat('alice_bob')), { type: 'text', text: 'x', senderId: 'alice' }));
    await assertFails(getDoc(doc(qiu('dave'), chat('alice_bob'))));
    await assertFails(setDoc(doc(qiu('dave'), chat('alice_dave')), text('dave')));
  });

  test('senderId must be the signed-in user', async () => {
    await assertFails(setDoc(doc(qiu('alice'), chat('alice_bob')), text('bob')));
  });

  test('only text, image and location messages are allowed', async () => {
    await assertFails(setDoc(doc(qiu('alice'), chat('alice_bob')), text('alice', { type: 'gif' })));
    await assertFails(setDoc(doc(qiu('alice'), chat('alice_bob', 'm2')), text('alice', { type: 'video' })));
    await assertSucceeds(setDoc(doc(qiu('alice'), chat('alice_bob', 'm3')), text('alice', { type: 'image', imageBase64: 'abc' })));
  });

  test('location messages need numeric coordinates', async () => {
    await assertFails(setDoc(doc(qiu('alice'), chat('alice_bob')), text('alice', { type: 'location', lat: 'x', lng: 'y' })));
    await assertSucceeds(setDoc(doc(qiu('alice'), chat('alice_bob', 'm2')), text('alice', { type: 'location', lat: 4.59, lng: 101.09 })));
  });

  test('messages cannot be edited or deleted', async () => {
    await assertSucceeds(setDoc(doc(qiu('alice'), chat('alice_bob')), text('alice')));
    await assertFails(updateDoc(doc(qiu('alice'), chat('alice_bob')), { text: 'edited' }));
    await assertFails(deleteDoc(doc(qiu('alice'), chat('alice_bob'))));
  });
});

// ---------------------------------------------------------------------------
describe('reviews', () => {
  const review = (reviewer, reviewee, extra = {}) => ({
    matchId: 'm1',
    reviewerId: reviewer,
    revieweeId: reviewee,
    rating: 5,
    comment: 'Great swap',
    createdAt: serverTimestamp(),
    ...extra,
  });

  test('a review is allowed after the trade is completed', async () => {
    await seedMatch({ status: 'completed' });
    await assertSucceeds(setDoc(doc(qiu('alice'), 'reviews/m1_alice'), review('alice', 'bob')));
  });

  test('a review is rejected before the trade is completed', async () => {
    await seedMatch({ status: 'confirmed' });
    await assertFails(setDoc(doc(qiu('alice'), 'reviews/m1_alice'), review('alice', 'bob')));
  });

  test('the document id must be matchId_reviewerUid', async () => {
    await seedMatch({ status: 'completed' });
    await assertFails(setDoc(doc(qiu('alice'), 'reviews/whatever'), review('alice', 'bob')));
    await assertFails(setDoc(doc(qiu('alice'), 'reviews/m1_bob'), review('alice', 'bob')));
  });

  test('cannot review as someone else or rate yourself', async () => {
    await seedMatch({ status: 'completed' });
    await assertFails(setDoc(doc(qiu('alice'), 'reviews/m1_alice'), review('bob', 'carol')));
    await assertFails(setDoc(doc(qiu('alice'), 'reviews/m1_alice'), review('alice', 'alice')));
  });

  test('only cycle members can review or be reviewed', async () => {
    await seedMatch({ status: 'completed' });
    await assertFails(setDoc(doc(qiu('dave'), 'reviews/m1_dave'), review('dave', 'bob')));
    await assertFails(setDoc(doc(qiu('alice'), 'reviews/m1_alice'), review('alice', 'dave')));
  });

  test('rating must be an integer from 1 to 5', async () => {
    await seedMatch({ status: 'completed' });
    for (const bad of [0, 6, 3.5, '5']) {
      await assertFails(setDoc(doc(qiu('alice'), 'reviews/m1_alice'), review('alice', 'bob', { rating: bad })));
    }
  });

  test('comment is capped at 300 characters', async () => {
    await seedMatch({ status: 'completed' });
    await assertFails(setDoc(doc(qiu('alice'), 'reviews/m1_alice'), review('alice', 'bob', { comment: 'x'.repeat(301) })));
    await assertSucceeds(setDoc(doc(qiu('alice'), 'reviews/m1_alice'), review('alice', 'bob', { comment: 'x'.repeat(300) })));
  });

  test('createdAt must be the server time', async () => {
    await seedMatch({ status: 'completed' });
    await assertFails(setDoc(doc(qiu('alice'), 'reviews/m1_alice'),
      review('alice', 'bob', { createdAt: Timestamp.fromDate(new Date('2020-01-01')) })));
  });

  test('unknown fields are rejected', async () => {
    await seedMatch({ status: 'completed' });
    await assertFails(setDoc(doc(qiu('alice'), 'reviews/m1_alice'), review('alice', 'bob', { admin: true })));
  });

  test('reviews are permanent: no edits, no deletes', async () => {
    await seedMatch({ status: 'completed' });
    await assertSucceeds(setDoc(doc(qiu('alice'), 'reviews/m1_alice'), review('alice', 'bob')));
    await assertFails(setDoc(doc(qiu('alice'), 'reviews/m1_alice'), review('alice', 'bob', { rating: 1 })));
    await assertFails(deleteDoc(doc(qiu('alice'), 'reviews/m1_alice')));
  });

  test('any QIU user can read reviews', async () => {
    await seed((db) => setDoc(doc(db, 'reviews/m1_alice'), { revieweeId: 'bob', rating: 4 }));
    await assertSucceeds(getDoc(doc(qiu('dave'), 'reviews/m1_alice')));
  });
});

// ---------------------------------------------------------------------------
describe('users', () => {
  test('a user can write their own document only', async () => {
    await assertSucceeds(setDoc(doc(qiu('alice'), 'users/alice'), { displayName: 'Alice' }));
    await assertFails(setDoc(doc(qiu('alice'), 'users/bob'), { displayName: 'Hacked' }));
  });

  test('a user can store their own consent choice', async () => {
    await assertSucceeds(setDoc(doc(qiu('alice'), 'users/alice'),
      { consentVersion: 1, consentAcceptedAt: serverTimestamp() }, { merge: true }));
  });

  test('QIU users can read other profiles', async () => {
    await seed((db) => setDoc(doc(db, 'users/bob'), { displayName: 'Bob' }));
    await assertSucceeds(getDoc(doc(qiu('alice'), 'users/bob')));
  });
});
