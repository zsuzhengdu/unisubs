// Amara, universalsubtitles.org
//
// Copyright (C) 2012 Participatory Culture Foundation
//
// This program is free software: you can redistribute it and/or modify
// it under the terms of the GNU Affero General Public License as
// published by the Free Software Foundation, either version 3 of the
// License, or (at your option) any later version.
//
// This program is distributed in the hope that it will be useful,
// but WITHOUT ANY WARRANTY; without even the implied warranty of
// MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
// GNU Affero General Public License for more details.
//
// You should have received a copy of the GNU Affero General Public License
// along with this program.  If not, see
// http://www.gnu.org/licenses/agpl-3.0.html.

goog.provide('unisubs.UnitOfWork');
goog.provide('unisubs.UnitOfWork.EventType');
/**
* @constructor
* @extends goog.events.EventTarget
*/
unisubs.UnitOfWork = function() {
    goog.events.EventTarget.call(this);
    this.instantiateLists_();
    this.everContainedWork_ = false;
};
goog.inherits(unisubs.UnitOfWork, goog.events.EventTarget);

unisubs.UnitOfWork.EventType = {
    WORK_PERFORMED: 'workperformed'
};

unisubs.UnitOfWork.prototype.instantiateLists_ = function() {
    this.updated_ = [];
    this.deleted_ = [];
    this.inserted_ = [];
    this.title = '';
};

unisubs.UnitOfWork.prototype.setTitle = function(title){
    this.title = title;
};

unisubs.UnitOfWork.prototype.registerNew = function(obj) {
    if (goog.array.contains(this.updated_, obj) ||
        goog.array.contains(this.deleted_, obj) ||
        goog.array.contains(this.inserted_, obj)) {
        throw new "registerNew failed";
    }

    this.everContainedWork_ = true;
    this.inserted_.push(obj);
    this.issueWorkEvent_();
};

unisubs.UnitOfWork.prototype.registerUpdated = function(obj) {
    if (goog.array.contains(this.deleted_, obj)) {
        throw new "registerUpdated failed";
    }

    if (!goog.array.contains(this.inserted_, obj) &&
        !goog.array.contains(this.updated_, obj)) {
        this.everContainedWork_ = true;
        this.updated_.push(obj);
        this.issueWorkEvent_();
    }
};

unisubs.UnitOfWork.prototype.registerDeleted = function(obj) {
    if (goog.array.contains(this.inserted_, obj)) {
        goog.array.remove(this.inserted_, obj);
    } else {
        this.everContainedWork_ = true;
        goog.array.remove(this.updated_, obj);
        if (!goog.array.contains(this.deleted_, obj)) {
            this.deleted_.push(obj);
        }
        this.issueWorkEvent_();
    }
};

unisubs.UnitOfWork.prototype.everContainedWork = function() {
    return this.everContainedWork_;
};

unisubs.UnitOfWork.prototype.containsWork = function() {
    return this.updated_.length > 0 ||
        this.deleted_.length > 0 ||
        this.inserted_.length > 0;
};

unisubs.UnitOfWork.prototype.clear = function() {
    this.instantiateLists_();
};

unisubs.UnitOfWork.prototype.issueWorkEvent_ = function() {
    this.dispatchEvent(unisubs.UnitOfWork.EventType.WORK_PERFORMED);
};

unisubs.UnitOfWork.prototype.getWork = function() {
    return {
        inserted: goog.array.clone(this.inserted_),
        updated: goog.array.clone(this.updated_),
        deleted: goog.array.clone(this.deleted_)
    };
};
